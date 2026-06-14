# Stage 1R Tunnel Setup

## Зачем нужен tunnel

Telegram webhook требует публичный HTTPS URL. Локальный API Jarvis слушает `http://localhost:8000`, поэтому для Stage 1R live smoke нужен временный HTTPS tunnel до локального порта `8000`.

## Вариант A: Cloudflare Tunnel

Проверить наличие:

```bash
command -v cloudflared || true
```

Запустить временный tunnel:

```bash
cloudflared tunnel --url http://localhost:8000
```

В выводе нужен URL вида:

```text
https://xxxxx.trycloudflare.com
```

Записать его в локальный `.env`:

```env
PUBLIC_BASE_URL=https://xxxxx.trycloudflare.com
```

После изменения `.env` пересоздать API и worker:

```bash
docker compose up -d --force-recreate api worker
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/ready
```

## Вариант B: ngrok

Проверить наличие:

```bash
command -v ngrok || true
```

Запустить tunnel:

```bash
ngrok http 8000
```

Взять HTTPS URL из вывода и записать его в `PUBLIC_BASE_URL` локального `.env`.

## После tunnel

Когда `PUBLIC_BASE_URL` указывает на публичный HTTPS URL:

```bash
uv run --python 3.12 --extra dev python scripts/bootstrap_real_env.py --dry-run
```

Затем установить webhook через проектный script, если он уже добавлен, или создать `scripts/set_telegram_webhook.py` по Stage 1R требованиям.

## Безопасность

- Не печатать `TELEGRAM_BOT_TOKEN`.
- Не печатать `TELEGRAM_WEBHOOK_SECRET`.
- Не коммитить `.env`.
- Не использовать URL без HTTPS для Telegram webhook.
