# Этап 1. Аудит Qadam Media Integration Lab

Дата аудита: 2026-10-09. Исходный код сохранён без изменений в [`legacy/`](../legacy) (запускается тем же `start-lab.ps1`, `.env` скопирован в `legacy/.env`). Это и есть путь отката.

## 1. Структура

| Путь | Назначение |
|---|---|
| `app/main.py` | FastAPI-приложение, все маршруты (≈200 строк) |
| `app/tiktok.py` | httpx-клиент TikTok (OAuth, user info, creator info, inbox upload, direct post, status) |
| `app/storage.py` | SQLite: таблицы `tokens` (одна строка `tiktok`) и `events`; Fernet-ключ в `data/token.key` |
| `app/config.py` | `pydantic-settings`, чтение `.env` |
| `static/` | Vanilla JS SPA в одном HTML (`index.html`, `app.js`), `privacy.html`, `terms.html` |
| `data/lab.db`, `data/token.key` | SQLite-база и ключ шифрования |

Зависимости: fastapi 0.115.0, uvicorn 0.30.6, httpx 0.27.2, python-multipart, pydantic-settings, cryptography. Тестов, Docker, миграций нет.

## 2. Карта функций

| Функция | Эндпоинт / модуль | Сохраняется в новой версии |
|---|---|---|
| Вход по общему паролю стенда | `POST /api/session` | Заменено: пользователи + сессии в БД (см. §4) |
| Статус интеграции | `GET /api/status` | Да → `/api/v1/dashboard`, `/api/v1/accounts` |
| Старт OAuth | `GET /oauth/tiktok/start` | Да → `/api/v1/tiktok/oauth/start` |
| Callback OAuth | `GET /oauth/tiktok/callback` | Да, **тот же публичный путь сохранён** (`/oauth/tiktok/callback`), чтобы не менять Redirect URI в TikTok Developer Portal |
| Проверка подключения | `POST /api/tiktok/test` (`/v2/user/info/`) | Да → при подключении и «Проверить» |
| Creator Info | `GET /api/tiktok/creator-info` | Да → `/api/v1/accounts/{id}/creator-info` |
| Обновление токена | `POST /api/tiktok/refresh` | Да + автоматическое (Celery beat) |
| Черновик в inbox | `POST /api/tiktok/upload-draft` (без UI) | Да, как режим публикации `UPLOAD_TO_INBOX` |
| Direct Post | `POST /api/tiktok/publish` | Да, через очередь Celery |
| Статус публикации | `GET /api/tiktok/publish-status/{id}` | Да, опрос в воркере + ручное «обновить» |
| Отключение | `DELETE /api/tiktok/disconnect` | Да + **реальный вызов revoke** |
| Журнал событий | `events` | Да → `publication_events` + `audit_logs` |
| Проверки перед публикацией (privacy ∈ options, длительность ≤ max) | `publish_video` | Да, расширены |
| Условия / Политика | `/terms`, `/privacy` | Да, те же URL и текст (нужны для ревью TikTok-приложения) |
| Health | `GET /health` | Да → `/health/live`, `/health/ready` (+ алиас `/health`) |

Использованные эндпоинты TikTok (проверены по официальной документации 2026-10-09):
`https://www.tiktok.com/v2/auth/authorize/`, `POST /v2/oauth/token/`, `POST /v2/oauth/revoke/`, `GET /v2/user/info/`, `POST /v2/post/publish/creator_info/query/`, `POST /v2/post/publish/video/init/`, `POST /v2/post/publish/inbox/video/init/`, `POST /v2/post/publish/status/fetch/`.

## 3. Данные для миграции

`data/lab.db`: таблицы `tokens` — **0 строк**, `events` — **0 строк**. Фактически переносить нечего, но скрипт `scripts/migrate_sqlite.py` реализован и протестирован на синтетической SQLite-базе: расшифровывает токены старым ключом (`token.key`), перешифровывает ключом из `ENCRYPTION_KEYS`, привязывает к указанному пользователю, события переносит в `audit_logs`.

## 4. Проблемы, технический долг и риски

### Безопасность (критичное)
1. **Единая «сессия» для всех.** `session_value()` = `HMAC(app_secret, lab_access_key)` — одно и то же значение навсегда: нельзя отозвать, нет срока на сервере, нет привязки к пользователю. Утечка cookie = вечный доступ.
2. **Нет защиты от перебора пароля** (rate limit отсутствует), нет CSRF-токенов (только `SameSite=Lax`), дефолты `change-me`.
3. **OAuth `state` только в cookie**: не привязан к пользователю, не одноразовый на сервере, не хранится со сроком; при ветке `error` cookie не удаляется; `delete_cookie` без тех же атрибутов. Не проверяются фактически выданные scopes.
4. **Ключ шифрования лежит рядом с шифртекстом** (`data/token.key` рядом с `lab.db`) — шифрование защищает только от случайного просмотра БД.
5. **Токен один на всю систему** (`provider='tiktok'`): single-tenant, нет владельца, нет контроля доступа.
6. **Утечка деталей ошибок клиенту**: `detail=str(exc)` отдаёт тексты исключений httpx (URL, коды).
7. Отключение не вызывает TikTok `oauth/revoke` — токены остаются действительными у TikTok.
8. Редакция журнала — только по трём ключам верхнего уровня.
9. Нет security headers, нет ограничения CORS/хостов, `cookie_secure` по умолчанию `False`.
10. `.env` с боевыми TikTok-ключами лежит в каталоге проекта в открытом виде (в репозитории исключён `.gitignore`, но `start-lab.ps1` ссылается на несуществующий `.env.example`).
11. Тип файла определяется по заголовку `Content-Type` клиента — подделывается, магические байты не проверяются.

### Надёжность / корректность
12. **Публикация синхронно внутри HTTP-запроса**, видео целиком в памяти (до 64 МБ), один чанк. Видео >64 МБ нарушают правила chunk TikTok (5–64 МБ, финальный до 128 МБ, ≤1000 чанков).
13. **Нет идемпотентности**: двойной клик/повторный запрос = дубль публикации. После перезапуска процесса статус публикации теряется (`publish_id` живёт только в JS-переменной браузера).
14. **Нет автообновления access token** (живёт 24 ч); `/api/tiktok/refresh` без обработки ошибок; ответ TikTok с `error` не проверяется для token endpoint; не сохраняются `expires_at`.
15. Нет rate limiting к TikTok (creator_info 20/мин, init 6/мин, status 30/мин на токен) и exponential backoff; нет различения временных/постоянных ошибок.
16. `video_cover_timestamp_ms=1000` захардкожено (ломается для видео <1 с).
17. Не учитываются `comment_disabled / duet_disabled / stitch_disabled` из Creator Info; не соблюдаются обязательные UX-требования Content Sharing Guidelines (ник создателя, **нет значения privacy по умолчанию**, тумблеры выключены по умолчанию, раскрытие коммерческого контента, Music Usage Confirmation).
18. Ограничение 5 пользователей/24 ч и «только SELF_ONLY» для неаудированных приложений не отражены в интерфейсе (только текстовое предупреждение). Ошибка `unaudited_client_can_only_post_to_private_accounts` не обрабатывается отдельно.
19. SQLite: `sqlite3.connect` на каждый вызов, блокирующий I/O в async-обработчиках, нет миграций, нет внешних ключей.
20. `@app.on_event("startup")` устарел; зависимости старые.

### Фронтенд
21. Vanilla JS с `innerHTML` (значение `<option value>` не экранируется), `confirm()`/`alert`-стиль подтверждений, нет доступности, нет тёмной темы, нет состояний загрузки/ошибок, «Журнал API» отдаёт сырой JSON, один экран на всё.

### Риски миграции
| Риск | Митигация |
|---|---|
| Смена Redirect URI сломает OAuth | Путь `/oauth/tiktok/callback` сохранён; домен тот же (`qadam-media.kz`) |
| Потеря токенов при смене ключа | Скрипт переноса расшифровывает старым ключом; сейчас токенов 0 |
| Новый вход вместо общего пароля | CLI `create-user` + опциональный bootstrap-админ из секретов |
| Дубли публикаций при ретраях воркера | Уникальный idempotency key, `SELECT … FOR UPDATE`, состояние `INITIATING` → при неопределённости пометка `NEEDS_REVIEW`, а не повторный init |
| Нельзя проверить реальный TikTok без доступа к Developer App | Mock-тесты + dev mock-сервер; список невыполненных живых проверок в README |

## 5. Решения

* Сохранить: бизнес-поток OAuth → Creator Info → валидация → Direct Post → статус; публичные URL `/terms`, `/privacy`, `/oauth/tiktok/callback`, `/health`.
* Заменить: хранилище (PostgreSQL), аутентификацию (пользователи + серверные сессии), синхронную публикацию (Celery), UI (React).
* Добавить: мульти-аккаунтность с владельцем, шифрование с ротацией ключей (MultiFernet), чанковую загрузку, идемпотентность, аудит.
