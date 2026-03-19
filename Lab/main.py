from telegram.ext import Application

import request_database
from config import (
    TELEGRAM_BOT_TOKEN,
    WEBHOOK_LISTEN,
    WEBHOOK_PATH,
    WEBHOOK_PORT,
    WEBHOOK_URL,
    configure_logging,
)
from handlers import register_handlers
from request_logger import log_system_event


async def post_init(app: Application) -> None:
    if not WEBHOOK_URL:
        await app.bot.delete_webhook(drop_pending_updates=False)


def main() -> None:
    configure_logging()
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not found. Add it to Lab/.env before starting the bot.")

    request_database.init_db()
    log_system_event(event_type="app_started", content="Telegram bot started")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    register_handlers(app)
    if WEBHOOK_URL:
        url_path = WEBHOOK_PATH.lstrip("/")
        webhook_url = f"{WEBHOOK_URL}/{url_path}" if url_path else WEBHOOK_URL
        app.run_webhook(
            listen=WEBHOOK_LISTEN,
            port=WEBHOOK_PORT,
            url_path=url_path,
            webhook_url=webhook_url,
        )
    else:
        app.run_polling()


if __name__ == "__main__":
    main()
