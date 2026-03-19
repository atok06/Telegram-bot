# Deploy

This project is ready for Docker-based deployment.

## Render

Render supports Docker deployments and `render.yaml` Blueprints:
- https://render.com/docs/docker
- https://render.com/docs/blueprint-spec

Steps:
1. Push this repository to GitHub, GitLab, or Bitbucket.
2. In Render, create a new Blueprint or Web Service from the repo.
3. If you use the included `render.yaml`, Render will create a Docker web service.
4. Set these secrets in Render:
   - `TELEGRAM_BOT_TOKEN`
   - `OPENROUTER_API_KEY`
5. Deploy.

Notes:
- The app auto-detects Render public URLs from `RENDER_EXTERNAL_URL`.
- Webhook path defaults to `/telegram`.
- The included Blueprint uses the `free` plan. Upgrade if you need an always-on instance.

## Railway

Railway can deploy the included `Dockerfile`.

Steps:
1. Create a new project from this repo.
2. Railway will detect the `Dockerfile`.
3. Add these variables:
   - `TELEGRAM_BOT_TOKEN`
   - `OPENROUTER_API_KEY`
   - `OPENROUTER_MODEL=xiaomi/mimo-v2-omni`
4. If Railway gives you a public domain, the app auto-detects it from Railway env vars and uses webhook mode.
5. If you deploy as a worker without a public domain, leave webhook settings empty and the bot will use polling.

## Koyeb

Koyeb can deploy the same `Dockerfile`.

Set:
- `TELEGRAM_BOT_TOKEN`
- `OPENROUTER_API_KEY`
- `OPENROUTER_MODEL=xiaomi/mimo-v2-omni`

If Koyeb exposes a public domain, the app can use webhook mode automatically when the domain env var is present.

## VPS

Run with Docker:

```bash
docker build -t atok-bot .
docker run -d \
  --name atok-bot \
  --restart unless-stopped \
  -e TELEGRAM_BOT_TOKEN=... \
  -e OPENROUTER_API_KEY=... \
  -e OPENROUTER_MODEL=xiaomi/mimo-v2-omni \
  atok-bot
```

Polling mode:
- Do not set `WEBHOOK_URL`.

Webhook mode:
- Set `WEBHOOK_URL=https://your-domain.com`
- Optionally set `WEBHOOK_PATH=/telegram`
- Expose the container port and route HTTPS traffic to it through a reverse proxy.
