import json
import logging
from datetime import datetime
import os
import tempfile
import asyncio
import requests
import subprocess

from pyrogram import Client, filters, idle
from pyrogram.types import Message

# Налаштування логування
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Завантаження конфігурації
def load_config():
    try:
        with open('config.json', 'r', encoding='utf-8') as config_file:
            return json.load(config_file)
    except Exception as e:
        logger.error(f"Помилка завантаження конфігурації: {e}")
        raise

# Глобальна конфігурація
CONFIG = load_config()

# Отримання значень з конфігурації
API_ID = CONFIG.get("telegram", {}).get("api_id")
API_HASH = CONFIG.get("telegram", {}).get("api_hash")
TELEGRAM_GROUP_ID = int(CONFIG["telegram"]["group_id"])
TELEGRAM_TOPIC_ID = int(CONFIG["telegram"]["topic_id"])
TELEGRAM_LOG_CHAT_ID = int(CONFIG["telegram"]["log_chat_id"])
GITHUB_TOKEN = CONFIG["github"]["token"]
GITHUB_OWNER = CONFIG["github"]["owner"]
GITHUB_REPO = CONFIG["github"]["repo"]
RELEASE_FILE_PATTERN = CONFIG["release"]["file_pattern"]

# Створення клієнта Pyrogram
app = Client(
    "4ifir_release_bot",
    api_id=API_ID,
    api_hash=API_HASH
)

# Словник для відстеження оброблених медіа-груп
processed_media_groups = {}

def add_file_to_release(upload_url, file_path, file_name, headers):
    """Додати файл до існуючого релізу."""
    try:
        with open(file_path, 'rb') as file:
            upload_headers = headers.copy()
            upload_headers["Content-Type"] = "application/zip"
            
            upload_response = requests.post(
                f"{upload_url}?name={file_name}",
                headers=upload_headers,
                data=file
            )
            upload_response.raise_for_status()
        
        logger.info(f"Файл {file_name} успішно додано до релізу")
        return True
    except Exception as e:
        logger.error(f"Помилка додавання файлу {file_name} до релізу: {e}")
        return False

def run_checker_script():
    """Запустити скрипт перевірки після успішного створення релізу."""
    try:
        # Запускаємо bash скрипт
        subprocess.run(['bash', os.path.expanduser('~/4ifir-checker/run_checker.sh')], check=True)
        logger.info("Скрипт перевірки успішно запущено")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Помилка при запуску скрипта перевірки: {e}")
        return False
    except Exception as e:
        logger.error(f"Неочікувана помилка при запуску скрипта перевірки: {e}")
        return False

def create_github_release(version: str, description: str, file_paths):
    """Створити реліз на GitHub і додати до нього файли."""
    # Спочатку створюємо реліз
    release_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
    
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    
    data = {
        "tag_name": f"v{version}",
        "target_commitish": "main",
        "name": "4IFIR",  # Фіксована назва релізу
        "body": description,
        "draft": False,
        "prerelease": False
    }
    
    try:
        # Створення релізу
        response = requests.post(release_url, headers=headers, json=data)
        response.raise_for_status()
        release_data = response.json()
        
        # Отримуємо URL для завантаження ассетів
        upload_url = release_data["upload_url"].split("{")[0]
        
        # Створюємо список для відстеження успішності завантаження всіх файлів
        all_uploads_successful = True
        
        # Завантаження всіх файлів як ассети
        for file_info in file_paths:
            file_path = file_info["path"]
            file_name = file_info["name"]
            
            success = add_file_to_release(upload_url, file_path, file_name, headers)
            if not success:
                all_uploads_successful = False
        
        if all_uploads_successful:
            logger.info(f"GitHub реліз v{version} успішно створено з усіма файлами")
        else:
            logger.warning(f"GitHub реліз v{version} створено, але деякі файли не були завантажені")
            
        return all_uploads_successful, release_data["html_url"]
    except Exception as e:
        logger.error(f"Помилка створення GitHub релізу: {e}")
        return False, None

@app.on_message(filters.chat(TELEGRAM_GROUP_ID) & filters.document)
async def handle_document(client, message: Message):
    """Обробити повідомлення з документом."""
    try:
        # Перевірка, чи повідомлення в потрібному топіку
        if hasattr(message, 'reply_to_message_id') and message.reply_to_message_id == TELEGRAM_TOPIC_ID:
            # Відправляємо лог у спеціальний чат для логів
            await client.send_message(
                TELEGRAM_LOG_CHAT_ID,
                f"📥 Отримано повідомлення в топіку {TELEGRAM_TOPIC_ID}. Починаю обробку..."
            )
        else:
            return
        
        # Якщо повідомлення належить до медіа-групи, передаємо його до іншого обробника
        if message.media_group_id:
            await handle_media_group_message(client, message)
            return
            
        # Перевіряємо наявність файлів
        if not message.document:
            return
        
        # Отримати текст повідомлення як реліз-ноут
        release_notes = message.caption if message.caption else "Новий реліз"
        
        # Отримати версію з часової мітки у форматі YYYY.MM.DD-HH.MM
        version = datetime.now().strftime("%Y.%m.%d-%H.%M")
        
        # Список файлів для додавання до релізу
        files_to_add = []
        
        # Перевіряємо документ
        file_name = message.document.file_name
        # Перевіряємо, чи це архів (.zip)
        if file_name.endswith('.zip'):
            # Створити тимчасовий файл
            with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_file:
                temp_path = temp_file.name
            
            # Завантажити файл
            await message.download(temp_path)
            
            files_to_add.append({"path": temp_path, "name": file_name})
            
            await client.send_message(
                TELEGRAM_LOG_CHAT_ID,
                f"📦 Файл {file_name} успішно завантажено у тимчасовий файл"
            )
        
        # Якщо знайдено файли для додавання до релізу
        if files_to_add:
            # Створити реліз на GitHub з файлами
            success, release_url = create_github_release(version, release_notes, files_to_add)
            
            # Видалити всі тимчасові файли
            for file_info in files_to_add:
                os.unlink(file_info["path"])
            
            if success:
                # Запускаємо скрипт перевірки
                checker_result = run_checker_script()
                
                # Відправляємо повідомлення в чат логів
                file_names_str = ", ".join([f"`{file_info['name']}`" for file_info in files_to_add])
                success_message = f"✅ Реліз v{version} успішно створено на GitHub!\n" + \
                                  f"📂 Додано файли: {file_names_str}\n" + \
                                  f"📎 {release_url}"
                
                # Додаємо інформацію про запуск скрипта перевірки
                if checker_result:
                    success_message += "\n🔍 Запущено скрипт перевірки"
                else:
                    success_message += "\n⚠️ Не вдалося запустити скрипт перевірки"
                
                await client.send_message(
                    TELEGRAM_LOG_CHAT_ID,
                    success_message
                )
            else:
                await client.send_message(
                    TELEGRAM_LOG_CHAT_ID,
                    "❌ Не вдалося створити реліз на GitHub. Перевірте логи."
                )
        else:
            await client.send_message(
                TELEGRAM_LOG_CHAT_ID,
                "ℹ️ Не знайдено архівів для додавання до релізу."
            )
    except Exception as e:
        error_message = f"❌ Сталася помилка при обробці повідомлення: {str(e)}"
        logger.error(error_message)
        await client.send_message(TELEGRAM_LOG_CHAT_ID, error_message)

async def handle_media_group_message(client, message: Message):
    """Обробити повідомлення з медіа-групи."""
    try:
        media_group_id = message.media_group_id
        
        # Перевіряємо, чи вже оброблена ця медіа-група нещодавно
        current_time = datetime.now()
        if media_group_id in processed_media_groups:
            last_processed_time = processed_media_groups[media_group_id]
            # Якщо обробляли менше 1 хвилини тому, пропускаємо
            if (current_time - last_processed_time).total_seconds() < 60:
                logger.info(f"Медіа-група {media_group_id} вже оброблена нещодавно. Пропускаємо.")
                return
        
        # Помічаємо цю медіа-групу як оброблену
        processed_media_groups[media_group_id] = current_time
        
        # Перевіряємо, чи є ZIP-файл у цьому повідомленні
        if not message.document or not message.document.file_name.endswith('.zip'):
            logger.info(f"Повідомлення в медіа-групі {media_group_id} не містить ZIP-архів. Пропускаємо.")
            return
        
        # Повідомляємо про початок обробки медіа-групи
        await client.send_message(
            TELEGRAM_LOG_CHAT_ID,
            f"📥 Обробка медіа-групи {media_group_id}. Зачекайте, щоб отримати всі файли..."
        )
        
        # Чекаємо 2 секунди, щоб переконатися, що всі повідомлення в медіа-групі вже отримані
        await asyncio.sleep(2)
        
        # Готуємо дані для релізу
        release_notes = message.caption if message.caption else "Новий реліз"
        version = datetime.now().strftime("%Y.%m.%d-%H.%M")
        files_to_add = []
        
        # Додаємо поточний файл
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_file:
            temp_path = temp_file.name
        
        # Завантажуємо файл
        await message.download(temp_path)
        
        files_to_add.append({"path": temp_path, "name": message.document.file_name})
        
        await client.send_message(
            TELEGRAM_LOG_CHAT_ID,
            f"📦 Файл {message.document.file_name} з медіа-групи завантажено у тимчасовий файл"
        )
        
        # Отримуємо історію повідомлень з цієї медіа-групи (за останні кілька хвилин)
        from datetime import timedelta
        five_minutes_ago = int((current_time - timedelta(minutes=5)).timestamp())
        
        try:
            async for msg in client.get_chat_history(TELEGRAM_GROUP_ID, limit=50):
                # Шукаємо повідомлення з тією ж медіа-групою
                if (msg.media_group_id == media_group_id and 
                    msg.id != message.id and  # не дублюємо поточне повідомлення
                    msg.document and 
                    msg.document.file_name.endswith('.zip')):
                    
                    # Створюємо новий тимчасовий файл для цього документа
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as new_temp_file:
                        new_temp_path = new_temp_file.name
                    
                    # Завантажуємо файл
                    await msg.download(new_temp_path)
                    
                    files_to_add.append({"path": new_temp_path, "name": msg.document.file_name})
                    
                    await client.send_message(
                        TELEGRAM_LOG_CHAT_ID,
                        f"📦 Додатковий файл {msg.document.file_name} з медіа-групи завантажено у тимчасовий файл"
                    )
        except Exception as e:
            logger.error(f"Помилка при отриманні додаткових повідомлень медіа-групи: {e}")
        
        # Якщо знайдено файли для додавання до релізу
        if files_to_add:
            # Створити реліз на GitHub з файлами
            success, release_url = create_github_release(version, release_notes, files_to_add)
            
            # Видалити всі тимчасові файли
            for file_info in files_to_add:
                os.unlink(file_info["path"])
            
            if success:
                # Запускаємо скрипт перевірки
                checker_result = run_checker_script()
                
                # Відправляємо повідомлення в чат логів
                file_names_str = ", ".join([f"`{file_info['name']}`" for file_info in files_to_add])
                success_message = f"✅ Реліз v{version} успішно створено на GitHub!\n" + \
                                  f"📂 Додано файли з медіа-групи: {file_names_str}\n" + \
                                  f"📎 {release_url}"
                
                # Додаємо інформацію про запуск скрипта перевірки
                if checker_result:
                    success_message += "\n🔍 Запущено скрипт перевірки"
                else:
                    success_message += "\n⚠️ Не вдалося запустити скрипт перевірки"
                
                await client.send_message(
                    TELEGRAM_LOG_CHAT_ID,
                    success_message
                )
            else:
                await client.send_message(
                    TELEGRAM_LOG_CHAT_ID,
                    "❌ Не вдалося створити реліз на GitHub. Перевірте логи."
                )
        else:
            await client.send_message(
                TELEGRAM_LOG_CHAT_ID,
                "ℹ️ В медіа-групі не знайдено архівів для релізу."
            )
            
    except Exception as e:
        error_message = f"❌ Сталася помилка при обробці медіа-групи: {str(e)}"
        logger.error(error_message)
        await client.send_message(TELEGRAM_LOG_CHAT_ID, error_message)

async def main():
    """Запуск бота."""
    await app.start()
    logger.info("Бот запущено. Очікуємо повідомлення...")
    
    # Залишаємося активними
    await idle()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())