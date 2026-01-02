import os
import tempfile
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
    """Get or create a connected Telethon client."""
    global telethon_client
    
    if telethon_client is None:
        telethon_client = TelegramClient(
            "4ifir_release_bot_telethon",
            API_ID,
            API_HASH
        )
        await telethon_client.start()
        logger.info("Telethon client started and initialized")
    
    # Ensure the client is still connected
    if not telethon_client.is_connected():
        logger.info("Telethon client was disconnected. Reconnecting...")
        await telethon_client.connect()
        
    return telethon_client

async def run_checker_script_async(message_id=None):
    """
    Запустити скрипт перевірки АСИНХРОННО.
    Не блокує основний потік бота.
    """
    try:
        script_path = CHECKER_SCRIPT_PATH
        
        if not os.path.exists(script_path):
            logger.error(f"Скрипт перевірки не знайдено за шляхом: {script_path}")
            return False
        
        args = ['bash', script_path]
        if message_id is not None:
            args.append(str(message_id))
            logger.info(f"Асинхронний запуск скрипта перевірки з ID повідомлення: {message_id}")
        else:
            logger.info("Асинхронний запуск скрипта перевірки без аргументів")

        # Використовуємо asyncio для запуску процесу
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # Чекаємо завершення (але це await не блокує весь event loop для інших задач)
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            logger.info(f"Скрипт перевірки успішно завершено.\nВивід:\n{stdout.decode()}")
            return True
        else:
            logger.error(f"Скрипт перевірки завершився з помилкою (код {process.returncode}).\nПомилка: {stderr.decode()}")
            return False
            
    except Exception as e:
        logger.error(f"Помилка при запуску скрипта перевірки: {e}")
        return False

# Зберігаємо стару назву для сумісності, але вона тепер викликає асинхронну версію
# (хоча краще викликати run_checker_script_async напряму з handlers)
def run_checker_script(message_id=None):
    # Ця функція залишена для зворотної сумісності, якщо десь викликається синхронно.
    # Але в handlers.py ми будемо використовувати нову async функцію.
    logger.warning("Викликано синхронну run_checker_script, що небажано.")
    return False 
        
async def download_file(bot, message_obj, file_name):
    """Завантажити файл через Bot API або Telethon."""
    try:
        if not ENABLE_FILE_DOWNLOAD:
            logger.info(f"Завантаження файлів вимкнено. Пропускаємо {file_name}.")
            return {"path": "dummy_path", "name": file_name}
        
        # 1. Спроба Bot API
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_file:
                temp_path = temp_file.name
            
            logger.info(f"Спроба завантажити {file_name} через Bot API...")
            
            file_id = message_obj.document.file_id
            file_info = await bot.get_file(file_id)
            await bot.download_file(file_info.file_path, temp_path)
            
            logger.info(f"Файл {file_name} завантажено через Bot API")
            return {"path": temp_path, "name": file_name}
            
        except Exception as e:
            logger.warning(f"Bot API не впорався ({e}). Переходимо на Telethon...")
            return await download_file_telethon(bot, message_obj, file_name, temp_path)
            
    except Exception as e:
        logger.error(f"Помилка завантаження файлу {file_name}: {e}")
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.unlink(temp_path)
        return None

def print_progress_bar(current, total, file_name):
    if total == 0: return
    percent = int(current * 100 / total)
    bar = '█' * int(20 * current / total) + '░' * (20 - int(20 * current / total))
    current_mb = current / 1024 / 1024
    total_mb = total / 1024 / 1024
    sys.stdout.write(f"\r⏳ {file_name}: [{bar}] {percent}% | {current_mb:.2f}/{total_mb:.2f} MB")
    sys.stdout.flush()
    if current == total: sys.stdout.write("\n")

async def progress_callback(current, total, file_name):
    print_progress_bar(current, total, file_name)

async def download_file_telethon(bot, message_obj, file_name, temp_path):
    try:
        client = await get_telethon_client()
        chat_id = message_obj.chat.id
        message_id = message_obj.message_id
        
        logger.info(f"Telethon завантаження: ID={message_id}, File={file_name}")
        
        telethon_message = await client.get_messages(chat_id, ids=message_id)
        if not telethon_message or not telethon_message.document:
            logger.error(f"Telethon не знайшов повідомлення {message_id}")
            if os.path.exists(temp_path): os.unlink(temp_path)
            return None
        
        progress_func = lambda c, t: asyncio.create_task(progress_callback(c, t, file_name))
        
        downloaded_path = await client.download_media(
            telethon_message,
            temp_path,
            progress_callback=progress_func
        )
        
        if not downloaded_path:
            if os.path.exists(temp_path): os.unlink(temp_path)
            return None
            
        return {"path": downloaded_path, "name": file_name}
    except Exception as e:
        logger.error(f"Telethon помилка: {e}")
        if os.path.exists(temp_path): os.unlink(temp_path)
        return None