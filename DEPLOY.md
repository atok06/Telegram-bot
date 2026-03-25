# Deploy

Бұл бот Docker арқылы deploy жасауға дайын.

## Міндетті env

- `TELEGRAM_BOT_TOKEN`

## Қосымша env

- `JOB_RESULTS_LIMIT=5`
- `ENABLE_PUBLIC_WEB_SEARCH=true`
- `WEBHOOK_URL=https://your-domain.com`
- `WEBHOOK_PATH=/telegram`

## Render

1. Репозиторийді Render-ге қосыңыз.
2. Docker service не Blueprint таңдаңыз.
3. `TELEGRAM_BOT_TOKEN` орнатыңыз.
4. Қажет болса `WEBHOOK_URL` немесе Render public URL қолданылады.

## Railway / VPS

```bash
docker build -t job-assistant-bot .
docker run -d \
  --name job-assistant-bot \
  --restart unless-stopped \
  -e TELEGRAM_BOT_TOKEN=... \
  job-assistant-bot
```

Егер public domain жоқ болса, бот polling режимінде жұмыс істейді.
