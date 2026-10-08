# Архитектура Qadam Media

Модульный монолит: один бэкенд-образ запускается в трёх ролях (API, Celery worker, Celery beat), фронтенд — статика за Nginx.

## 1. Компоненты и границы

| Компонент | Ответственность | Связи |
|---|---|---|
| `nginx` | TLS, заголовки безопасности, rate limit, маршрутизация `/api`, `/oauth`, `/` | frontend, backend |
| `frontend` | React SPA (статика), никаких секретов | только `/api/v1` |
| `backend` | HTTP API, аутентификация, валидация, постановка задач | postgres, redis, TikTok (OAuth, Creator Info) |
| `worker` | Direct Post: init → чанковая загрузка → опрос статуса | postgres, redis, TikTok, том `media_data` |
| `beat` | Расписание: sweep, refresh токенов, очистка | redis |
| `postgres` | Единственное хранилище состояния | внутренняя сеть `data` |
| `redis` | Брокер/результаты Celery, лимиты запросов (API и TikTok) | внутренняя сеть `data` |

Сети: `data` (`internal: true`) — только postgres/redis/backend/worker/beat; `edge` — nginx, frontend, и сервисы, которым нужен выход в интернет к TikTok.
Наружу опубликованы только 80/443 nginx.

Слои бэкенда (`backend/app`): `api/` (маршруты, зависимости) → `services/` (бизнес-логика и SQL-запросы; отдельный слой репозиториев не вводился — запросов немного, и он только добавил бы косвенность) → `models/` (SQLAlchemy 2, async);
`integrations/tiktok/` — типизированный клиент без знания о БД; `workers/` — тонкие обёртки Celery над сервисами; `core/` — конфиг, криптография, редакция логов, безопасность.
Сервисы принимают `AsyncSession` и сами коммитят; воркеры работают с собственными короткими транзакциями.

## 2. Модель данных (PostgreSQL)

UUID-ключи (`gen_random_uuid()`), `TIMESTAMPTZ`, внешние ключи с индексами (это проверяет тест), CHECK-ограничения на статусы.

| Таблица | Назначение | Ключевое |
|---|---|---|
| `users` | Пользователи | `email` уникален и в нижнем регистре (CHECK), Argon2-хэш, счётчик неудач/блокировка |
| `sessions` | Серверные сессии | в БД только HMAC-хэш токена; idle- и absolute-срок; отзыв |
| `connected_accounts` | Аккаунты TikTok | уникальность `(user_id, provider, open_id)`; `access_token_enc`/`refresh_token_enc` — Fernet; сроки жизни; статус `active/needs_reauth/revoked` |
| `oauth_states` | Одноразовый `state` | хэш, пользователь, срок, `consumed_at` |
| `media_assets` | Загруженные видео | имя файла `<uuid>.<ext>` генерируется сервером, sha256, длительность; мягкое удаление |
| `publications` | Задачи публикации | `UNIQUE(user_id, idempotency_key)`, частичный `UNIQUE(tiktok_publish_id)`, `upload_url_enc`, прогресс `uploaded_bytes`, `lease_until` |
| `publication_events` | Таймлайн публикации | переходы статусов, ответы TikTok, повторы (секреты редактируются) |
| `audit_logs` | Журнал действий | пользователь, действие, IP, user-agent, детали |

Секреты в открытом виде не хранятся нигде: токены TikTok и `upload_url` — шифртекст Fernet (`MultiFernet`, ротация ключей), токены сессий и OAuth `state` — keyed-хэш.

## 3. Аутентификация и сессии

* Вход → случайный 256-бит токен в cookie `qm_session` (**HttpOnly, Secure, SameSite=Lax**), в БД — только HMAC-хэш.
* CSRF: подписанный double-submit — cookie `qm_csrf` + заголовок `X-CSRF-Token`, значение привязано к сессии (HMAC от токена сессии), плюс проверка `Origin/Referer`.
* Блокировка аккаунта после 5 неудач (15 мин), rate limit входа (IP, Redis) и в nginx, одинаковые ответы для «нет пользователя»/«неверный пароль» (в т. ч. выравнивание времени).
* Смена пароля завершает все остальные сессии.

## 4. TikTok: потоки

### OAuth
1. `POST /api/v1/tiktok/oauth/start` (CSRF) создаёт `state` (32 байта, хэш в БД, TTL 10 мин, привязка к пользователю) и возвращает URL `https://www.tiktok.com/v2/auth/authorize/…`.
2. TikTok → `GET /oauth/tiktok/callback` (путь сохранён от старого стенда). Сервер: атомарно «съедает» `state` (`UPDATE … WHERE consumed_at IS NULL AND expires_at > now() RETURNING`), проверяет владельца по сессии, обменивает `code` на сервере (`client_secret` никогда не покидает бэкенд), запрашивает профиль, шифрует токены, делает upsert аккаунта и редиректит на `/accounts?connected=…` или `?oauth_error=<код>`.
3. Токены: access 24 ч, refresh 365 дней. Обновление — под `SELECT … FOR UPDATE`, параллельные вызовы делают один refresh; `invalid_grant` → `needs_reauth`; новый refresh-токен сохраняется, если TikTok его ротирует. Beat каждые 15 мин обновляет токены, истекающие в ближайшие 2 часа.
4. Отключение: `POST /v2/oauth/revoke/`, затем локальное удаление токенов (даже если revoke не прошёл).

### Публикация (Direct Post)
Конечные автоматы и гарантии — в докстринге [`backend/app/services/publishing.py`](../backend/app/services/publishing.py).

```
QUEUED ─▶ INITIATING ─▶ UPLOADING ─▶ PROCESSING ─▶ PUBLISHED
   │           │                          └──────▶ INBOX_DELIVERED (режим «в черновики»)
   │           └── исход неизвестен ─────────────▶ NEEDS_REVIEW      любой этап ─▶ FAILED
   └─▶ CANCELLED
```

* `POST /api/v1/publications` требует `Idempotency-Key`; повтор с тем же ключом возвращает исходную запись (200). Дополнительно блокируется публикация того же видео в тот же аккаунт (`409 duplicate_publication`).
* **Защита от дублей в воркере**: `init` вызывается только из `QUEUED`, перед вызовом строка переводится в `INITIATING` с «арендой» (`lease_until`) и коммитится. Повторно доставленная задача видит `UPLOADING` (докачивает), `PROCESSING` (ничего не делает) или просроченную аренду `INITIATING` — тогда `NEEDS_REVIEW`, а не второй `init`. Таймаут чтения при `init` (запрос мог дойти) → `NEEDS_REVIEW`; ошибка соединения/5xx/429 → безопасный повтор.
* Загрузка: `PUT upload_url` последовательно, `Content-Range`, чанки по правилам TikTok (файл ≤ 64 МБ — одним запросом, иначе 32 МБ-чанки, последний ≤ 128 МБ, ≤ 1000), докачка с последнего подтверждённого чанка, `416` синхронизирует смещение, `403/404` → `upload_url_expired`.
* Статус: `POST /v2/post/publish/status/fetch/` с экспоненциальным интервалом (10 с → 5 мин), таймаут 6 ч → `NEEDS_REVIEW`; причины `fail_reason` переводятся на русский.
* Лимиты на токен (Redis, чуть ниже официальных): creator_info 18/мин, init 5/мин, status 25/мин. `429` → повтор через `Retry-After`; прочие временные ошибки — backoff с jitter, не более 6 попыток, затем `FAILED` (никогда не «потеря»).
* Брокер: `acks_late`, `reject_on_worker_lost`, `prefetch=1`, `visibility_timeout=4ч`; `sweep` раз в минуту переотправляет потерянные задачи (сообщения в брокере, упавший воркер).

### Требования TikTok к форме (Content Sharing Guidelines) — реализованы
Свежий Creator Info при показе формы, отображение ника, привилегии из `privacy_level_options` **без значения по умолчанию**, переключатели комментариев/Duet/Stitch выключены по умолчанию и блокируются по `*_disabled`,
раскрытие коммерческого контента («Ваш бренд»/«Брендированный контент», минимум один пункт, бренд-контент нельзя «Только я»), Music Usage Confirmation, подтверждение перед отправкой, ограничение неаудированного приложения `SELF_ONLY`.

## 5. Контракт API (`/api/v1`)

Ошибки: `{"error": {"code", "message", "details?"}}`; 422 не возвращает присланные значения. Изменяющие запросы требуют `X-CSRF-Token`.

| Метод и путь | Назначение |
|---|---|
| `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`, `POST /auth/register`* | Сессия (*регистрация выключена по умолчанию) |
| `POST /auth/password`, `GET /auth/sessions`, `DELETE /auth/sessions/{id}` | Безопасность |
| `POST /tiktok/oauth/start` → `{authorization_url}` | Начало OAuth |
| `GET /oauth/tiktok/callback` (вне `/api/v1`) | Возврат из TikTok |
| `GET /accounts`, `GET /accounts/{id}`, `GET /accounts/{id}/creator-info`, `POST /accounts/{id}/refresh`, `DELETE /accounts/{id}` | Аккаунты (токены в ответах не присутствуют) |
| `POST /media` (multipart `video`, `duration_seconds?`), `GET /media`, `GET/DELETE /media/{id}` | Видео |
| `POST /publications` (`Idempotency-Key`), `GET /publications?status&account_id&limit&offset`, `GET /publications/{id}`, `POST /publications/{id}/cancel`, `POST /publications/{id}/retry` | Публикации |
| `GET /dashboard`, `GET /audit-logs`, `GET /meta` | Обзор, журнал, публичные параметры |
| `GET /health/live`, `/health/ready` (`/health` — алиас) | Состояние (ready проверяет Postgres и Redis; через nginx снаружи доступен только `live`) |

Схема OpenAPI доступна в разработке по `/api/docs`; в production отключена.

## 6. Безопасность — сводка

| Угроза | Мера |
|---|---|
| Кража/подмена сессии | HttpOnly+Secure+SameSite cookie, хэш токена в БД, отзыв, idle/absolute-сроки |
| CSRF | Подписанный double-submit + проверка Origin |
| Перебор паролей | Argon2, блокировка, лимиты Redis и nginx |
| Подмена OAuth | Одноразовый серверный `state`, привязка к пользователю, TTL, атомарное «съедание» |
| Утечка токенов | Fernet с ротацией ключей, секреты в Docker secrets, редакция логов/событий, токены не уходят в браузер/localStorage/JSON-ответы |
| Вредоносные файлы | Проверка по содержимому (magic bytes), лимит размера на потоке, серверные имена `<uuid>.<ext>`, проверка пути (path traversal) |
| Доступ к чужим данным | Все запросы фильтруются по `user_id`; чужой ресурс → 404 |
| Clickjacking/XSS | CSP `script-src 'self'`, `frame-ancestors 'none'`, `nosniff`, отсутствие `dangerouslySetInnerHTML` |
| Компрометация контейнера | Non-root, `read_only`, `cap_drop: ALL`, `no-new-privileges`, внутренняя сеть для данных |
| Подмена Host | Nginx пробрасывает каноничный `Host`, неизвестные хосты отбрасываются (444), `TrustedHostMiddleware` |

Известные компромиссы: CSP допускает `style-src 'unsafe-inline'` (инлайн-стили библиотек UI); `--forwarded-allow-ips '*'` у uvicorn безопасно только потому, что бэкенд недоступен вне сети nginx;
первичный процесс Postgres стартует от root и сразу понижает привилегии (штатное поведение официального образа).

## 7. Соответствие критериям завершения

| Критерий | Статус |
|---|---|
| React ↔ FastAPI | ✅ проверено вручную в браузере и e2e на живом стеке |
| PostgreSQL как основная БД, SQLite исключён | ✅ (SQLite остался только в `legacy/` и как read-only источник миграции) |
| Миграции Alembic | ✅ вверх/вниз, нет дрейфа схемы (тест), выполняются сервисом `migrate` |
| TikTok OAuth по действующему API | ✅ реализовано по документации и mock‑тестам; ⚠️ живой TikTok не проверялся (см. README) |
| Direct Post + фон | ✅ полный цикл на mock (Celery worker), ⚠️ живой TikTok не проверялся |
| Docker Compose | ✅ dev и prod подняты и проверены (healthchecks, non-root, закрытые порты, TLS на самоподписанном сертификате) |
| Секреты не раскрываются клиенту | ✅ тесты: токены не в ответах API, не в БД открыто, не в логах/событиях |
| Тесты | ✅ backend 232, frontend 82, e2e 22 + 1 полностековый |
