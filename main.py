from telegram.ext import Application, MessageHandler, filters
import logging

from config import TELEGRAM_TOKEN, TELEGRAM_TOPIC_ID, logger
from handlers import handle_document

def main():
    """Запуск бота."""
    # Створюємо додаток
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Add handlers for documents
    # Add filter for messages with required message_thread_id
    application.add_handler(
        MessageHandler(
            filters.Document.ALL & 
            filters.Document.MimeType("application/zip") & 
            ~filters.COMMAND &
            filters.ChatType.SUPERGROUP,  # Check that it is a supergroup
            handle_document
        )
    )
    
    # Also handle edited messages with ZIP documents
    application.add_handler(
        MessageHandler(
            filters.UpdateType.EDITED_MESSAGE &
            filters.Document.ALL & 
            filters.Document.MimeType("application/zip") & 
            ~filters.COMMAND &
            filters.ChatType.SUPERGROUP,
            handle_document
        )
    )
    
    # Add additional handler for ZIP files with other MIME types
    application.add_handler(
        MessageHandler(
            filters.Document.FileExtension("zip") & 
            ~filters.COMMAND &
            filters.ChatType.SUPERGROUP,  # Check that it is a supergroup
            handle_document
        )
    )
    
    # Also handle edited messages for ZIP files with other MIME types
    application.add_handler(
        MessageHandler(
            filters.UpdateType.EDITED_MESSAGE &
            filters.Document.FileExtension("zip") & 
            ~filters.COMMAND &
            filters.ChatType.SUPERGROUP,
            handle_document
        )
    )
    
    logger.info(f"Бот запущено. Очікуємо повідомлення в топіку ID: {TELEGRAM_TOPIC_ID}...")
    
    # Запускаємо бота без використання asyncio.run
    application.run_polling()

if __name__ == "__main__":
    main()