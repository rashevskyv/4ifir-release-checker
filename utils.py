import subprocess
import os
import tempfile
from config import logger

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

async def download_and_save_file(message, file_name=None):
    """Завантажити файл з повідомлення і зберегти у тимчасовий файл."""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_file:
            temp_path = temp_file.name
            
        # Завантажити файл
        await message.download(temp_path)
        
        actual_file_name = file_name or message.document.file_name
        
        logger.info(f"Файл {actual_file_name} успішно завантажено у тимчасовий файл")
        return {
            "path": temp_path, 
            "name": actual_file_name
        }
    except Exception as e:
        logger.error(f"Помилка при завантаженні файлу {file_name or 'невідомий'}: {e}")
        return None