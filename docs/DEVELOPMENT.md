# Development workflow

Create focused branches from `development` and use Conventional Commits. Keep one
behavioral concern per commit, add tests with the behavior they protect, and run
backend lint plus frontend typecheck before requesting review.

Never commit `.env`, encryption keys, TikTok credentials, database dumps or media.
Use `.env.example` for documented configuration and `secrets/` for local files.

Useful checks:

```text
cd backend && .venv/Scripts/python -m ruff check app tests tests_unit
cd backend && .venv/Scripts/python -m pytest --confcutdir=tests_unit tests_unit
cd frontend && npm run typecheck && npm test
docker compose --env-file .env.example config --quiet
```
