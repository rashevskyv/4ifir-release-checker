import json
import logging

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

# Важливі файли, які потрібно включити в кожний реліз
REQUIRED_FILES = ["AIO.zip", "4IFIX.zip"]