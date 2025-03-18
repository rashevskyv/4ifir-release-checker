import subprocess
import os
import tempfile
from datetime import datetime
from config import logger, TELEGRAM_LOG_CHAT_ID

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

async def download_and_save_file(client, message, file_name=None):
    """Завантажити файл з повідомлення і зберегти у тимчасовий файл з консольним індикатором прогресу."""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_file:
            temp_path = temp_file.name
        
        actual_file_name = file_name or message.file.name
        file_size = message.file.size
        
        # Функція для оновлення статусу завантаження в консолі
        async def progress_callback(current, total):
            percent = current * 100 / total
            # Створюємо графічний індикатор прогресу
            bar_length = 30
            filled_length = int(bar_length * current / total)
            bar = '█' * filled_length + '░' * (bar_length - filled_length)
            
            # Розраховуємо швидкість (Kb/s)
            if not hasattr(progress_callback, 'start_time'):
                progress_callback.start_time = datetime.now()
                progress_callback.last_current = 0
                progress_callback.last_time = progress_callback.start_time
            
            now = datetime.now()
            time_diff = (now - progress_callback.last_time).total_seconds()
            
            if time_diff > 0.5:  # Оновлюємо кожні 0.5 секунди
                bytes_diff = current - progress_callback.last_current
                speed = bytes_diff / time_diff / 1024  # KB/s
                
                elapsed = (now - progress_callback.start_time).total_seconds()
                if current > 0:
                    estimated_total = elapsed * total / current
                    remaining = estimated_total - elapsed
                else:
                    remaining = 0
                
                # Форматуємо розмір у зручному вигляді
                if total < 1024 * 1024:
                    size_text = f"{total / 1024:.1f} KB"
                    current_text = f"{current / 1024:.1f} KB"
                else:
                    size_text = f"{total / 1024 / 1024:.1f} MB"
                    current_text = f"{current / 1024 / 1024:.1f} MB"
                
                # Очищаємо поточний рядок та виводимо прогрес
                print(f"\r⬇️ {actual_file_name} [{bar}] {percent:.1f}% ({current_text}/{size_text}) | {speed:.1f} KB/s | ETA: {int(remaining)}s   ", end='', flush=True)
                
                # Оновлюємо останні значення
                progress_callback.last_current = current
                progress_callback.last_time = now
        
        # Завантажити файл за допомогою Telethon з індикатором прогресу
        await client.download_media(message, temp_path, progress_callback=progress_callback)
        
        # Фінальне повідомлення про завершення
        print(f"\r✅ Файл {actual_file_name} ({file_size/1024/1024:.1f} MB) успішно завантажено               ")
        
        logger.info(f"Файл {actual_file_name} успішно завантажено у тимчасовий файл")
        return {
            "path": temp_path, 
            "name": actual_file_name
        }
    except Exception as e:
        print(f"\r❌ Помилка при завантаженні файлу {file_name or 'невідомий'}: {e}               ")
        logger.error(f"Помилка при завантаженні файлу {file_name or 'невідомий'}: {e}")
        return None