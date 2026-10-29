# Configuration

All configuration lives in `src/app/core/config.py` as a single typed `Settings` model.

## Rules

1. **Nothing reads `os.environ`.** If it is configurable, it is a field on `Settings`.
2. **Access it through `get_settings()`** (cached), or the `SettingsDep` dependency in
   routes. Do not construct `Settings()` at import time in application code.
3. **Every field has a type and, where sensible, a constraint.** A bad value fails at
   startup with a clear message instead of at 3am with a `TypeError`.
4. **Document it in `.env.example`** in the same commit.

## Adding a setting

```python
# src/app/core/config.py
webhook_timeout_seconds: float = Field(default=5.0, gt=0)
```

```bash
# .env.example
WEBHOOK_TIMEOUT_SECONDS=5.0
```

Field name ↔ environment variable is a direct, case-insensitive mapping. Lists accept
both `A,B` and `["A","B"]`.

## Environments

`ENVIRONMENT` is one of `local`, `test`, `staging`, `production`. The staging and
production values trigger extra validation that refuses to start with:

* `DEBUG=true`
* a non-JSON log renderer
* a placeholder or short `SECRET_KEY`
* `*` in `CORS_ORIGINS`

Production also disables `/docs`, `/redoc` and `/openapi.json`.

## Secrets

`.env` is git-ignored and is for local development only. In deployed environments,
inject configuration as environment variables from your platform's secret store
(Kubernetes Secrets, SSM, Vault, Doppler…). Never commit a real secret, and generate
`SECRET_KEY` per environment:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Rotating `SECRET_KEY` invalidates every issued JWT.

## Settings in tests

Build an explicit `Settings(...)` instead of mutating the environment — see the
`settings` fixture in `tests/conftest.py`. `get_settings.cache_clear()` resets the
singleton if a test genuinely needs to.
