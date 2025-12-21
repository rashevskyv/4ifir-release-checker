import os
import asyncio
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config import (
    TELEGRAM_GROUP_ID, TELEGRAM_TOPIC_ID, 
    TELEGRAM_LOG_CHAT_ID, REQUIRED_FILES, logger,
    ENABLE_GITHUB_RELEASE, ENABLE_CHECKER_SCRIPT,
    ENABLE_FILE_DOWNLOAD
)
from github_api import (
    create_github_release, download_required_files_from_previous_releases
)
from utils import run_checker_script, download_file

async def process_release_logic(context: ContextTypes.DEFAULT_TYPE, files_list, release_notes, message_id):
    """
    Універсальна функція створення релізу, яка приймає вже готовий список файлів.
    Використовується і для одиночних повідомлень, і для медіа-груп.
    """
    try:
        version = datetime.now().strftime("%Y.%m.%d-%H.%M")
        
        # Створюємо словник для швидкого пошуку наявних файлів
        files_dict = {f["name"]: f for f in files_list}
        file_names_present = [f["name"] for f in files_list]
        
        logger.info(f"Початок формування релізу. Наявні файли: {file_names_present}")

        # Перевіряємо, чи всі необхідні файли є наявні
        missing_required_files = []
        for required_file in REQUIRED_FILES:
            if required_file not in files_dict:
                missing_required_files.append(required_file)
        
        if missing_required_files:
            await context.bot.send_message(
                chat_id=TELEGRAM_LOG_CHAT_ID,
                text=f"⚠️ Відсутні необхідні файли: {', '.join(missing_required_files)}. Завантажую їх з попередніх релізів..."
            )
            
            # Завантажуємо відсутні файли з попередніх релізів
            previous_files = download_required_files_from_previous_releases()
            
            for req_file in missing_required_files:
                if req_file in previous_files:
                    file_info = previous_files[req_file]
                    files_list.append(file_info)
                    files_dict[req_file] = file_info
                    
                    await context.bot.send_message(
                        chat_id=TELEGRAM_LOG_CHAT_ID,
                        text=f"📥 Файл {req_file} успішно підтягнуто з історії"
                    )
                else:
                    await context.bot.send_message(
                        chat_id=TELEGRAM_LOG_CHAT_ID,
                        text=f"❓ Не вдалося знайти файл {req_file} ні в поточному повідомленні, ні в історії"
                    )

        # Якщо є файли для релізу
        if files_list:
            success = False
            release_url = None
            file_names_str = ", ".join([f"`{file_info['name']}`" for file_info in files_list])
            
            if ENABLE_GITHUB_RELEASE:
                success, release_url = create_github_release(version, release_notes, files_list)
                
                if success:
                    success_message = (
                        f"✅ **Реліз v{version} успішно створено!**\n"
                        f"📂 Файли: {file_names_str}\n"
                        f"📎 [Посилання на реліз]({release_url})"
                    )
                else:
                    await context.bot.send_message(
                        chat_id=TELEGRAM_LOG_CHAT_ID,
                        text="❌ Не вдалося створити реліз на GitHub. Перевірте логи."
                    )
                    return # Не видаляємо файли, щоб можна було розібратися, або видаляємо в finally
            else:
                success_message = (
                    f"✅ Файли отримано (GitHub реліз вимкнено).\n"
                    f"📂 Файли: {file_names_str}"
                )
                success = True
            
            # Видаляємо тимчасові файли
            for file_info in files_list:
                if os.path.exists(file_info["path"]) and file_info["path"] != "dummy_path":
                    try:
                        os.unlink(file_info["path"])
                    except Exception as e:
                        logger.error(f"Не вдалося видалити тимчасовий файл {file_info['path']}: {e}")

            # Запуск скрипта перевірки
            if success and ENABLE_CHECKER_SCRIPT:
                checker_result = run_checker_script(message_id)
                if checker_result:
                    success_message += f"\n🔍 Скрипт перевірки запущено (ID: {message_id})"
                else:
                    success_message += "\n⚠️ Помилка запуску скрипта перевірки"
            
            await context.bot.send_message(
                chat_id=TELEGRAM_LOG_CHAT_ID,
                text=success_message,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await context.bot.send_message(
                chat_id=TELEGRAM_LOG_CHAT_ID,
                text="ℹ️ Немає файлів для створення релізу."
            )

    except Exception as e:
        logger.error(f"Помилка в логіці релізу: {e}")
        await context.bot.send_message(
            chat_id=TELEGRAM_LOG_CHAT_ID,
            text=f"❌ Критична помилка при створенні релізу: {e}"
        )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Головний обробник документів."""
    try:
        message = update.effective_message
        
        # 1. Перевірки чату і топіку
        if message.chat.id != int(TELEGRAM_GROUP_ID):
            return
        if message.message_thread_id and message.message_thread_id != int(TELEGRAM_TOPIC_ID):
            return
            
        # 2. Перенаправлення на обробку медіа-групи, якщо це вона
        if message.media_group_id:
            await handle_media_group_message(update, context)
            return

        # 3. Обробка одиночного файлу
        message_id = message.message_id
        file_name = message.document.file_name
        
        if not file_name.endswith('.zip'):
            return

        logger.info(f"Обробка одиночного файлу: {file_name}")
        await context.bot.send_message(
            chat_id=TELEGRAM_LOG_CHAT_ID,
            text=f"📥 Отримано одиночний файл {file_name}. ID: {message_id}"
        )

        files_to_add = []
        if ENABLE_FILE_DOWNLOAD:
            file_info = await download_file(context.bot, message, file_name)
            if file_info:
                files_to_add.append(file_info)
        else:
             # Якщо завантаження вимкнено - імітуємо
            files_to_add.append({"path": "dummy_path", "name": file_name})

        release_notes = message.caption if message.caption else "Новий реліз"
        
        # Викликаємо спільну логіку
        await process_release_logic(context, files_to_add, release_notes, message_id)

    except Exception as e:
        logger.error(f"Помилка в handle_document: {e}")

async def handle_media_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обробити повідомлення з медіа-групи.
    Накопичує файли і створює один реліз.
    """
    try:
        message = update.effective_message
        media_group_id = message.media_group_id
        message_id = message.message_id
        file_name = message.document.file_name

        if not file_name.endswith('.zip'):
            return

        # Ініціалізація сховища для цієї медіа-групи
        if 'media_groups_cache' not in context.bot_data:
            context.bot_data['media_groups_cache'] = {}
        
        cache = context.bot_data['media_groups_cache']

        # Якщо це перше повідомлення з групи, створюємо запис
        if media_group_id not in cache:
            cache[media_group_id] = {
                'files': [],
                'caption': message.caption if message.caption else "Новий реліз",
                'main_message_id': message_id,
                'processing_started': False
            }
            logger.info(f"Створено нову групу накопичення для ID {media_group_id}")

        # Оновлюємо кепшн, якщо він є (іноді кепшн тільки на першому фото/файлі)
        if message.caption:
            cache[media_group_id]['caption'] = message.caption

        # ЗАВАНТАЖЕННЯ ФАЙЛУ (робиться паралельно для кожного повідомлення)
        if ENABLE_FILE_DOWNLOAD:
            # Логуємо тільки початок, щоб не спамити
            logger.info(f"Початок завантаження файлу {file_name} з групи {media_group_id}")
            file_info = await download_file(context.bot, message, file_name)
            if file_info:
                # Додаємо файл у спільний список цієї групи
                cache[media_group_id]['files'].append(file_info)
                await context.bot.send_message(
                    chat_id=TELEGRAM_LOG_CHAT_ID,
                    text=f"📦 Файл {file_name} додано до черги обробки групи."
                )
        else:
            cache[media_group_id]['files'].append({"path": "dummy_path", "name": file_name})

        # ЛОГІКА "ЛІДЕРА" (Debouncing)
        # Перевіряємо, чи вже запущено процес очікування для цієї групи
        if cache[media_group_id]['processing_started']:
            # Якщо "лідер" вже чекає, ми просто додали файл і виходимо.
            logger.info(f"Файл {file_name} додано до існуючої сесії обробки.")
            return

        # Якщо ми тут - це повідомлення стало ініціатором таймера
        cache[media_group_id]['processing_started'] = True
        
        await context.bot.send_message(
            chat_id=TELEGRAM_LOG_CHAT_ID,
            text=f"⏳ Отримано перший файл групи. Чекаю 10 секунд для отримання решти..."
        )

        # Чекаємо поки Telegram надішле, а бот завантажить інші файли
        await asyncio.sleep(10)

        # --- КРИТИЧНА СЕКЦІЯ ПІСЛЯ ОЧІКУВАННЯ ---
        
        # Перевіряємо, чи дані все ще існують (про всяк випадок)
        if media_group_id not in cache:
            logger.error(f"Кеш для групи {media_group_id} зник після очікування!")
            return

        group_data = cache[media_group_id]
        collected_files = group_data['files']
        final_caption = group_data['caption']
        main_msg_id = group_data['main_message_id']

        logger.info(f"Завершено очікування групи {media_group_id}. Зібрано файлів: {len(collected_files)}")

        # Видаляємо з кешу, щоб уникнути повторної обробки або витоку пам'яті
        del cache[media_group_id]

        # Запускаємо створення релізу з повним списком файлів
        if collected_files:
            await process_release_logic(context, collected_files, final_caption, main_msg_id)
        else:
            await context.bot.send_message(
                chat_id=TELEGRAM_LOG_CHAT_ID,
                text="⚠️ Група оброблена, але файли не було завантажено."
            )

    except Exception as e:
        error_message = f"❌ Помилка при обробці медіа-групи: {str(e)}"
        logger.error(error_message)
        await context.bot.send_message(chat_id=TELEGRAM_LOG_CHAT_ID, text=error_message)