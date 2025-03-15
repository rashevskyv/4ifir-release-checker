import asyncio
import logging
from pyrogram import Client, idle

from config import API_ID, API_HASH, logger, TELEGRAM_GROUP_ID
from handlers import handle_document
from pyrogram import filters

async def main():
    """Запуск бота."""
    # Створення клієнта Pyrogram
    app = Client(
        "4ifir_release_bot",
        api_id=API_ID,
        api_hash=API_HASH
    )
    
    # Реєстрація обробників повідомлень
    app.on_message(filters.chat(TELEGRAM_GROUP_ID) & filters.document)(handle_document)
    
    await app.start()
    logger.info("Бот запущено. Очікуємо повідомлення...")
    
    # Залишаємося активними
    await idle()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())