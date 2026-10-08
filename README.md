# Qadam Media

Платформа для публикации видео в TikTok через официальные **Login Kit** и **Content Posting API**:
React-интерфейс, FastAPI-бэкенд, PostgreSQL, фоновые задачи на Celery/Redis, всё за Nginx с HTTPS.

> Это миграция бывшего «Integration Lab» (один файл `main.py`, SQLite, один общий пароль) на production-архитектуру.
> Старый стенд сохранён нетронутым в [`legacy/`](legacy) — это путь отката. Аудит и решения: [docs/AUDIT.md](docs/AUDIT.md), устройство системы: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

```
браузер ──HTTPS──▶ nginx ──▶ frontend (React, статика)
                      └────▶ backend (FastAPI) ──▶ PostgreSQL
                                   │  └──────────▶ Redis ◀── worker (Celery) ──▶ TikTok API
                                   └─ общий том media_data ◀──┘     beat (расписание)
```


## 👥 Contributors

Special thanks to the developers who contributed to Qadam Media.

- [@bagdau](https://github.com/bagdau) — Project Owner
- [@zamdirectortech-max](https://github.com/zamdirectortech-max) — Developer
- [@napoleonrs22](https://github.com/napoleonrs22) — Developer

## Что умеет

| Раздел | Возможности |
|---|---|
| Вход | Пользователи с паролями (Argon2), серверные сессии, блокировка после 5 неудачных попыток, CSRF, список и завершение сессий |
| Аккаунты TikTok | OAuth 2.0 (Login Kit) с одноразовым `state`, серверный обмен кода, шифрование токенов, автообновление, **реальный revoke** при отключении |
| Публикация | Загрузка видео (проверка по содержимому, чанки), параметры из Creator Info, Direct Post или «в черновики», коммерческий контент, подтверждение перед отправкой |
| Фон | Очередь Celery: загрузка чанками с докачкой, опрос статуса с backoff, лимиты TikTok, защита от дублей, автоочистка файлов |
| История | Статусы в реальном времени, таймлайн событий, повтор/отмена, журнал действий |
| Безопасность | HttpOnly/Secure/SameSite cookie, строгие CORS и CSP, rate limiting, редакция секретов в логах, аудит |

## Быстрый старт (разработка)

Нужны Docker и Docker Compose.

```bash
cp .env.example .env
# 1) вставьте ключ шифрования в ENCRYPTION_KEYS:
python -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
# 2) задайте BOOTSTRAP_ADMIN_PASSWORD (≥12 символов) — по нему создастся первый администратор
docker compose up --build
```

Откройте <http://localhost:8080> и войдите как `BOOTSTRAP_ADMIN_EMAIL`. PostgreSQL и Redis порты наружу **не публикуют**:
`docker compose exec postgres psql -U qadam`.

### Без TikTok Developer App: локальная имитация

TikTok требует HTTPS-redirect и проверку приложения, поэтому для разработки есть mock (только dev, в production-режиме бэкенд отказывается принимать подменённые адреса TikTok):

```bash
# в .env
TIKTOK_CLIENT_KEY=mock
TIKTOK_CLIENT_SECRET=mock-secret
TIKTOK_API_BASE=http://mock-tiktok:9000/v2
TIKTOK_AUTHORIZE_URL=http://localhost:8080/mock-tiktok/v2/auth/authorize/
TIKTOK_SCOPES=user.info.basic,video.publish,video.upload
docker compose --profile mock up --build
```

Кнопка «Подключить TikTok» откроет страницу согласия mock; опубликованное видео «обрабатывается» ~8 секунд.

## Production

1. **TikTok for Developers**: создайте приложение, добавьте продукты **Login Kit** и **Content Posting API**, scopes `user.info.basic` и `video.publish`
   (для режима «в черновики» ещё `video.upload`). Зарегистрируйте точный Redirect URI: `https://ВАШ-ДОМЕН/oauth/tiktok/callback`
   — путь совпадает с путём старого стенда.
2. Заполните `.env`: `SERVER_NAME`, `PUBLIC_URL=https://…`, `TIKTOK_REDIRECT_URI`, `TIKTOK_CLIENT_KEY`, `BOOTSTRAP_ADMIN_EMAIL`, `LETSENCRYPT_EMAIL`.
3. Секреты (Docker secrets, файлы в `./secrets`, не переменные окружения):
   ```bash
   scripts/init-secrets.sh        # Windows: scripts\init-secrets.ps1
   # затем впишите Client Secret TikTok в secrets/tiktok_client_secret
   ```
   **Сделайте резервную копию `secrets/encryption_keys`** — без него токены в БД не расшифровать.
4. TLS. nginx не стартует без сертификата, поэтому сначала положите любой: тестовый самоподписанный — `scripts/gen-dev-cert.sh ВАШ-ДОМЕН`,
   либо свой боевой в `infrastructure/nginx/certs/{fullchain,privkey}.pem`. Для Let's Encrypt после запуска стека (шаг 5) выполните
   `scripts/issue-cert.sh` — он выпустит сертификат через HTTP-01, положит его в `infrastructure/nginx/certs` и перезагрузит nginx;
   для продления запускайте его из cron раз в сутки (до окончания срока ничего не меняет).
5. Запуск: `docker compose -f compose.prod.yaml up -d --build`. Миграции применяет одноразовый сервис `migrate` до старта приложения.
6. Проверка: `docker compose -f compose.prod.yaml ps` (все сервисы `healthy`), `https://ВАШ-ДОМЕН/health/live`.

`TIKTOK_CLIENT_AUDITED=false` (по умолчанию) отражает ограничения неаудированного приложения: публикация только с видимостью «Только я»
в закрытые аккаунты, до 5 пользователей за 24 часа. Поставьте `true` **только после** аудита TikTok.

### Эксплуатация

| Задача | Команда |
|---|---|
| Создать пользователя | `docker compose -f compose.prod.yaml exec backend python -m app.cli create-user user@example.com --name "Имя"` |
| Логи | `docker compose -f compose.prod.yaml logs -f backend worker` (JSON, токены вырезаны) |
| Бэкап БД | `docker compose -f compose.prod.yaml exec -T postgres pg_dump -U qadam -Fc qadam > qadam-$(date +%F).dump` |
| Восстановление | `docker compose -f compose.prod.yaml exec -T postgres pg_restore -U qadam -d qadam --clean < qadam.dump` |
| Ротация ключа шифрования | добавьте новый ключ **первым** в `secrets/encryption_keys` (через запятую), `docker compose -f compose.prod.yaml up -d`, затем `exec backend python -m app.cli rotate-encryption`, после — удалите старый ключ |
| Обновление | `git pull && docker compose -f compose.prod.yaml up -d --build` (graceful shutdown: воркер дожидается текущей загрузки до 120 с) |
| Публикация «зависла» | статус `NEEDS_REVIEW` значит «неизвестно, принял ли TikTok запрос» — проверьте профиль/черновики TikTok и только потом повторите |

Тома: `pg_data`, `redis_data`, `media_data` (загруженные видео; чистятся автоматически), `beat_data`, `letsencrypt`.

## Перенос данных из старого стенда

В `legacy/data/lab.db` на момент аудита **0 токенов и 0 событий** — переносить было нечего. Если у вас на сервере есть живая база:

```bash
docker compose -f compose.prod.yaml run --rm -v /путь/к/legacy/data:/legacy:ro backend \
  python -m app.cli migrate-sqlite --sqlite /legacy/lab.db --key /legacy/token.key --user admin@example.com --dry-run
# убедитесь в сводке, затем без --dry-run
```

Токены расшифровываются старым ключом и перешифровываются новым; события попадают в журнал действий; повторный запуск безопасен; исходные файлы только читаются.

**Откат**: `legacy/` запускается как раньше (`legacy/start-lab.ps1`, ваш `legacy/.env`). Новый стек можно остановить `docker compose down` (тома сохраняются).
Старый `.env` в корне не изменялся; из него новому стеку понадобятся только `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REDIRECT_URI`.

## Тесты

```bash
# backend: 232 теста на настоящем PostgreSQL (миграции прогоняются Alembic'ом), TikTok — respx-mock
cd backend && python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt     # Linux: .venv/bin/pip
docker run -d --name qadam-test-pg -e POSTGRES_PASSWORD=testpw -e POSTGRES_USER=qadam -e POSTGRES_DB=qadam_test -p 127.0.0.1:54329:5432 postgres:17-alpine
.venv/Scripts/python -m pytest                       # TEST_DATABASE_URL переопределяет адрес

# frontend: юнит/компонентные тесты и e2e по production-бандлу (API подменяется на уровне сети)
cd frontend && npm ci && npm test && npx playwright install chromium && npm run e2e

# полный стек: React → nginx → FastAPI → Postgres → Celery → mock TikTok
docker compose --profile mock up -d        # с mock-настройками из раздела выше
E2E_STACK=1 E2E_EMAIL=admin@example.com E2E_PASSWORD=… npx playwright test --project=desktop
```

Покрытие: OAuth (state: подделка, повтор, чужой, просроченный; отказ; сбой обмена), токены (истечение, ротация, параллельный refresh, `invalid_grant`, revoke),
публикация (идемпотентность, двойной клик, падение воркера, неоднозначный таймаут, докачка чанков, 416/403/429/5xx, неаудированное приложение, дневной лимит),
БД (миграции вверх/вниз, отсутствие дрейфа схемы, ограничения, индексы на FK), безопасность (CSRF, Origin, rate limit, блокировка, утечки секретов в логах/событиях),
интерфейс (валидация, подтверждения опасных действий, правила TikTok к форме, открытый redirect, выход, mobile).

## Структура

```
backend/          FastAPI: api/ core/ db/ models/ schemas/ services/ integrations/tiktok/ workers/ + alembic/ tests/ devtools/
frontend/         React + TS + Vite + Tailwind + shadcn/ui: app/ components/ features/ hooks/ services/ types/ utils/ + e2e/
infrastructure/   nginx (prod с TLS, dev без)
scripts/          init-secrets, gen-dev-cert
compose.yaml      разработка (Vite HMR, uvicorn --reload, mock TikTok по профилю)
compose.prod.yaml production (Docker secrets, read-only FS, cap_drop ALL, healthchecks)
legacy/           прежний стенд (откат)
```

## Что НЕ проверено (честно)

Доступа к TikTok Developer App в этой среде не было, поэтому **интеграция не объявляется полностью проверенной**. Эндпоинты, поля, лимиты и правила чанков
сверены с официальной документацией TikTok for Developers на 2026‑10‑09 и покрыты mock‑тестами, но на реальном TikTok остаётся проверить:

1. Полный OAuth на HTTPS‑домене с зарегистрированным Redirect URI и реальное согласие (`scopes` в callback, `refresh_token` после refresh).
2. Direct Post на тестовом аккаунте с видимостью `SELF_ONLY` (Creator Info → init → загрузка → `PUBLISH_COMPLETE`, форма `publicaly_available_post_id`).
3. Режим «в черновики» (`video.upload`) — нужен включённый продукт и scope.
4. Многочанковая загрузка файла > 64 МБ (логика проверена юнит‑ и mock‑тестами по правилам TikTok, но не на живом `upload_url`).
5. Поведение `unaudited_client_can_only_post_to_private_accounts` и лимита «5 пользователей / 24 ч» на вашем приложении; затем аудит приложения TikTok.
6. Отзыв доступа в настройках TikTok (`auth_removed`) и `access_token_invalid` на живом токене.
7. Let's Encrypt‑сертификат и работа за вашим реальным доменом/файрволом (в проверке использовался самоподписанный сертификат на `localhost`).
8. Не реализовано сознательно: `PULL_FROM_URL`, фото‑посты, планирование на будущее, мульти‑организации.
