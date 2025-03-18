import asyncio
import logging
from telethon import TelegramClient, events

from config import API_ID, API_HASH, logger, TELEGRAM_GROUP_ID
from handlers import handle_document

async def main():
    """Запуск бота."""
    # Створення клієнта Telethon
    client = TelegramClient(
        "4ifir_release_bot",
        API_ID,
        API_HASH
    )
    
    # Реєстрація обробників повідомлень
    client.add_event_handler(
        handle_document,
        events.NewMessage(chats=TELEGRAM_GROUP_ID, func=lambda e: e.file is not None)
    )
    
    await client.start()
    logger.info("Бот запущено. Очікуємо повідомлення...")
    
    # Залишаємося активними
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())