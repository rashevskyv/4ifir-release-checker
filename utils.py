import os
import tempfile
import subprocess
from datetime import datetime
import logging
import asyncio
import sys
from telethon import TelegramClient

from config import (
    logger, API_ID, API_HASH, TELEGRAM_LOG_CHAT_ID, 
    ENABLE_FILE_DOWNLOAD, CHECKER_SCRIPT_PATH
)

# Глобальний клієнт Telethon
telethon_client = None

async def get_telethon_client():
    """Отримати клієнт Telethon."""
    global telethon_client
    
    if telethon_client is None:
        # Створюємо клієнт Telethon
        telethon_client = TelegramClient(
            "4ifir_release_bot_telethon",
            API_ID,
            API_HASH
        )
        await telethon_client.start()
        logger.info("Telethon клієнт запущено")
        
    return telethon_client

def run_checker_script(message_id=None):
    """Запустити скрипт перевірки.
    
    Args:
        message_id (int, optional): ID повідомлення в Telegram для відповіді. 
                                   Якщо вказано, буде передано скрипту.
    """
    try:
        # Отримуємо шлях до скрипта з конфігурації
        script_path = CHECKER_SCRIPT_PATH
        
        # Перевіряємо, чи існує скрипт
        if not os.path.exists(script_path):
            logger.error(f"Скрипт перевірки не знайдено за шляхом: {script_path}")
            return False
        
        # Визначаємо, з якими параметрами запускати скрипт
        if message_id is not None:
            # Якщо ID повідомлення вказано, передаємо його скрипту як аргумент
            logger.info(f"Запуск скрипта перевірки з ID повідомлення: {message_id}")
            result = subprocess.run(['bash', script_path, str(message_id)], capture_output=True, text=True)
        else:
            # Інакше запускаємо без додаткових аргументів
            logger.info("Запуск скрипта перевірки без додаткових аргументів")
            result = subprocess.run(['bash', script_path], capture_output=True, text=True)
        
        if result.returncode == 0:
            logger.info(f"Скрипт перевірки успішно запущено. Вивід: {result.stdout}")
            return True
        else:
            logger.error(f"Скрипт перевірки завершився з помилкою. Код: {result.returncode}, Помилка: {result.stderr}")
            return False
    except Exception as e:
        logger.error(f"Помилка при запуску скрипта перевірки: {e}")
        return False
        
async def download_file(bot, message_obj, file_name):
    """Завантажити файл через Bot API або Telethon."""
    try:
        # Перевіряємо, чи увімкнене завантаження файлів
        if not ENABLE_FILE_DOWNLOAD:
            logger.info(f"Завантаження файлів вимкнено в налаштуваннях. Пропускаємо завантаження {file_name}.")
            # Відправляємо повідомлення користувачу
            await bot.send_message(
                chat_id=TELEGRAM_LOG_CHAT_ID,
                text=f"ℹ️ Завантаження файлів вимкнено в налаштуваннях. Пропускаємо завантаження {file_name}."
            )
            return {
                "path": "dummy_path",
                "name": file_name
            }
        
        # Спочатку пробуємо використовувати Bot API
        try:
            # Створюємо тимчасовий файл
            with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_file:
                temp_path = temp_file.name
            
            # Відправляємо повідомлення про початок завантаження
            progress_msg = await bot.send_message(
                chat_id=TELEGRAM_LOG_CHAT_ID,
                text=f"⏳ Починаємо завантаження файлу {file_name} через Bot API..."
            )
            
            # Завантажуємо файл через Bot API
            file_id = message_obj.document.file_id
            file_info = await bot.get_file(file_id)
            downloaded_file = await bot.download_file(file_info.file_path, temp_path)
            
            # Повідомляємо про завершення
            await bot.edit_message_text(
                chat_id=TELEGRAM_LOG_CHAT_ID,
                message_id=progress_msg.message_id,
                text=f"✅ Файл {file_name} успішно завантажено через Bot API у тимчасовий файл"
            )
            
            logger.info(f"Файл {file_name} успішно завантажено через Bot API у тимчасовий файл {temp_path}")
            
            return {
                "path": temp_path,
                "name": file_name
            }
        except Exception as e:
            logger.error(f"Помилка завантаження файлу {file_name} через Bot API: {e}")
            logger.info(f"Спроба завантажити файл {file_name} за допомогою Telethon")
            
            # Якщо є повідомлення про прогрес, оновлюємо його
            if 'progress_msg' in locals():
                await bot.edit_message_text(
                    chat_id=TELEGRAM_LOG_CHAT_ID,
                    message_id=progress_msg.message_id,
                    text=f"⚠️ Не вдалося завантажити через Bot API: {str(e)}\n⏳ Спробуємо через Telethon..."
                )
            
            # Завантажуємо через Telethon
            return await download_file_telethon(bot, message_obj, file_name)
    except Exception as e:
        logger.error(f"Помилка завантаження файлу {file_name}: {e}")
        # Видаляємо тимчасовий файл у разі помилки
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.unlink(temp_path)
        return None

def print_progress_bar(current, total, file_name):
    """Вивести прогрес-бар у консоль."""
    # Визначаємо, скільки відсотків вже завантажено
    percent = int(current * 100 / total)
    
    # Будуємо прогрес-бар
    bar_length = 20
    filled_length = int(bar_length * current / total)
    bar = '█' * filled_length + '░' * (bar_length - filled_length)
    
    # Обчислюємо розмір в МБ
    current_mb = current / 1024 / 1024
    total_mb = total / 1024 / 1024
    
    # Готуємо рядок прогресу
    progress_str = f"\r⏳ Завантаження {file_name}: [{bar}] {percent}% | {current_mb:.2f} МБ / {total_mb:.2f} МБ"
    
    # Виводимо прогрес-бар в консоль (з перезаписом того ж рядка)
    sys.stdout.write(progress_str)
    sys.stdout.flush()
    
    # Якщо завантаження завершено, переходимо на новий рядок
    if current == total:
        sys.stdout.write("\n")

async def progress_callback(current, total, file_name):
    """Callback-функція для відстеження прогресу завантаження."""
    # Вивести прогрес-бар у консоль
    print_progress_bar(current, total, file_name)

async def download_file_telethon(bot, message_obj, file_name):
    """Завантажити файл за допомогою Telethon."""
    try:
        # Отримуємо клієнт Telethon
        client = await get_telethon_client()
        
        # Створюємо тимчасовий файл
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_file:
            temp_path = temp_file.name
        
        # Отримуємо дані для завантаження
        chat_id = message_obj.chat.id
        message_id = message_obj.message_id
        
        # Виводимо основну інформацію для логування
        logger.info(f"Телетон завантаження: chat_id={chat_id}, message_id={message_id}, file_name={file_name}")
        
        # Відправляємо повідомлення про початок завантаження в телеграм
        progress_msg = await bot.send_message(
            chat_id=TELEGRAM_LOG_CHAT_ID,
            text=f"⏳ Підготовка до завантаження файлу {file_name} через Telethon..."
        )
        
        # Отримуємо повідомлення через Telethon
        telethon_message = await client.get_messages(chat_id, ids=message_id)
        
        if not telethon_message or not telethon_message.document:
            logger.error(f"Не вдалося знайти документ у повідомленні через Telethon")
            await bot.edit_message_text(
                chat_id=TELEGRAM_LOG_CHAT_ID,
                message_id=progress_msg.message_id,
                text=f"❌ Помилка: Не вдалося знайти документ у повідомленні через Telethon"
            )
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            return None
        
        # Повідомляємо про початок завантаження
        await bot.edit_message_text(
            chat_id=TELEGRAM_LOG_CHAT_ID,
            message_id=progress_msg.message_id,
            text=f"⏳ Починаємо завантаження файлу {file_name} через Telethon... Прогрес відображається в консолі."
        )
        
        # Функція для відстеження прогресу завантаження (тільки консоль)
        progress_callback_func = lambda current, total: asyncio.create_task(
            progress_callback(current, total, file_name)
        )
        
        # Завантажуємо файл з відстеженням прогресу
        downloaded_path = await client.download_media(
            telethon_message,
            temp_path,
            progress_callback=progress_callback_func
        )
        
        if not downloaded_path or not os.path.exists(downloaded_path):
            logger.error(f"Помилка під час завантаження файлу через Telethon")
            await bot.edit_message_text(
                chat_id=TELEGRAM_LOG_CHAT_ID,
                message_id=progress_msg.message_id,
                text=f"❌ Помилка: Не вдалося завантажити файл через Telethon"
            )
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            return None
        
        # Повідомляємо про успішне завантаження
        await bot.edit_message_text(
            chat_id=TELEGRAM_LOG_CHAT_ID,
            message_id=progress_msg.message_id,
            text=f"✅ Файл {file_name} успішно завантажено через Telethon"
        )
        
        logger.info(f"Файл {file_name} успішно завантажено через Telethon у тимчасовий файл {downloaded_path}")
        
        return {
            "path": downloaded_path,
            "name": file_name
        }
    except Exception as e:
        logger.error(f"Помилка завантаження файлу {file_name} через Telethon: {e}")
        
        if 'progress_msg' in locals():
            await bot.edit_message_text(
                chat_id=TELEGRAM_LOG_CHAT_ID,
                message_id=progress_msg.message_id,
                text=f"❌ Помилка завантаження файлу {file_name} через Telethon: {str(e)}"
            )
        
        # Видаляємо тимчасовий файл у разі помилки
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.unlink(temp_path)
        return None