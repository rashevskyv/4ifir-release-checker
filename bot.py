import json
import logging
from datetime import datetime
import os
import tempfile
import asyncio
import requests

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

def create_github_release(version: str, description: str, file_path):
    """Створити реліз на GitHub і додати до нього файл."""
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
        
        # Завантаження файлу як ассет
        with open(file_path, 'rb') as file:
            upload_headers = headers.copy()
            upload_headers["Content-Type"] = "application/zip"
            
            upload_response = requests.post(
                f"{upload_url}?name={RELEASE_FILE_PATTERN}",
                headers=upload_headers,
                data=file
            )
            upload_response.raise_for_status()
        
        logger.info(f"GitHub реліз v{version} успішно створено з файлом {RELEASE_FILE_PATTERN}")
        return True
    except Exception as e:
        logger.error(f"Помилка створення GitHub релізу: {e}")
        return False

@app.on_message(filters.chat(TELEGRAM_GROUP_ID) & filters.document)
async def handle_document(client, message: Message):
    """Обробити повідомлення з документом."""
    try:
        # Перевіряємо, чи це файл 4IFIR.zip
        if message.document.file_name != RELEASE_FILE_PATTERN:
            return
        
        # Перевірка, чи повідомлення в потрібному топіку
        if hasattr(message, 'reply_to_message_id') and message.reply_to_message_id == TELEGRAM_TOPIC_ID:
            # Відправляємо лог у спеціальний чат для логів
            await client.send_message(
                TELEGRAM_LOG_CHAT_ID,
                f"📥 Отримано файл {RELEASE_FILE_PATTERN} в топіку {TELEGRAM_TOPIC_ID}. Починаю обробку..."
            )
        else:
            return
        
        # Отримати текст повідомлення як реліз-ноут
        release_notes = message.caption if message.caption else "Новий реліз"
        
        # Отримати версію з часової мітки у форматі YYYY.MM.DD-HH.MM
        version = datetime.now().strftime("%Y.%m.%d-%H.%M")
        
        # Створити тимчасовий файл
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_file:
            temp_path = temp_file.name
            
        # Завантажити файл
        await message.download(temp_path)
        await client.send_message(
            TELEGRAM_LOG_CHAT_ID,
            f"📦 Файл успішно завантажено у тимчасовий файл"
        )
        
        # Створити реліз на GitHub з файлом
        success = create_github_release(version, release_notes, temp_path)
        
        # Видалити тимчасовий файл
        os.unlink(temp_path)
        
        if success:
            release_url = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/tag/v{version}"
            # Відправляємо повідомлення в чат логів
            await client.send_message(
                TELEGRAM_LOG_CHAT_ID,
                f"✅ Реліз v{version} успішно створено на GitHub!\n" + 
                f"📎 {release_url}"
            )
        else:
            await client.send_message(
                TELEGRAM_LOG_CHAT_ID,
                "❌ Не вдалося створити реліз на GitHub. Перевірте логи."
            )
            
    except Exception as e:
        error_message = f"❌ Сталася помилка при обробці повідомлення: {str(e)}"
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