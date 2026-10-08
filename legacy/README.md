# Qadam Media Integration Lab

Отдельный стенд для реальной публикации видео через TikTok Login Kit и Direct Post API.

## Как работает TikTok-интеграция

1. Браузер открывает `/oauth/tiktok/start`.
2. Сервер создаёт случайный `state` и перенаправляет пользователя на TikTok.
3. Пользователь разрешает `user.info.basic` и `video.publish`.
4. TikTok возвращает одноразовый `code` на зарегистрированный HTTPS Redirect URI.
5. Сервер проверяет `state`, обменивает `code` на access/refresh tokens и шифрует их в SQLite.
6. Стенд получает допустимые параметры публикации через Creator Info API.
7. Пользователь добавляет описание и видео и нажимает «Опубликовать в TikTok».
8. Сервер инициирует Direct Post, загружает видео и отслеживает обработку по `publish_id`.

Client Secret и пользовательские токены никогда не отправляются в браузер и не записываются в журнал.

## Подготовка TikTok Developer App

- Создайте приложение на TikTok for Developers.
- Добавьте Login Kit и Content Posting API.
- Зарегистрируйте точный HTTPS callback: `https://ВАШ-ДОМЕН/oauth/tiktok/callback`.
- Добавьте scopes `user.info.basic,video.publish`.
- Для публичной прямой публикации потребуется аудит приложения TikTok. Неаудированные приложения ограничены приватной видимостью.

## Локальный запуск

```powershell
Copy-Item .env.example .env
# Заполните .env
.\start-lab.ps1
```

Откройте `http://localhost:8100`. TikTok требует HTTPS callback, поэтому для реального OAuth используйте ваш тестовый HTTPS-домен или защищённый tunnel и укажите его одинаково в TikTok Developer Portal и `.env`.

## Сервер

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8100
```

Разместите приложение за Nginx/Caddy с HTTPS. Не публикуйте `.env`, папку `data` и файл `data/token.key`.

## Безопасность

- задайте длинные `LAB_ACCESS_KEY` и `APP_SECRET`;
- оставьте `COOKIE_SECURE=true` на сервере;
- ограничьте доступ к стенду по IP или VPN;
- используйте отдельное тестовое TikTok-приложение;
- сначала тестируйте на отдельном TikTok-аккаунте;
- не загружайте контент с чужими правами или нежелательными водяными знаками.
