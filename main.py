from telegram.ext import Application, MessageHandler, filters
import logging

from config import TELEGRAM_TOKEN, TELEGRAM_TOPIC_ID, logger
from handlers import handle_document

def main():
    """Запуск бота."""
    # Створюємо додаток
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Додаємо обробник для документів
    # Додаємо фільтр на повідомлення з потрібним message_thread_id
    application.add_handler(
        MessageHandler(
            filters.Document.ALL & 
            filters.Document.MimeType("application/zip") & 
            ~filters.COMMAND &
            filters.ChatType.SUPERGROUP,  # Перевіряємо, що це суперогрупа
            handle_document
        )
    )
    
    # Можна додати додаткові обробники для ZIP-файлів з іншими MIME-типами
    application.add_handler(
        MessageHandler(
            filters.Document.FileExtension("zip") & 
            ~filters.COMMAND &
            filters.ChatType.SUPERGROUP,  # Перевіряємо, що це суперогрупа
            handle_document
        )
    )
    
    logger.info(f"Бот запущено. Очікуємо повідомлення в топіку ID: {TELEGRAM_TOPIC_ID}...")
    
    # Запускаємо бота без використання asyncio.run
    application.run_polling()

if __name__ == "__main__":
    main()