import os
from datetime import datetime, timedelta
import asyncio

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

# Словник для відстеження оброблених медіа-груп
processed_media_groups = {}

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробити повідомлення з документом."""
    try:
        message = update.effective_message
        
        # Перевірка, чи повідомлення в потрібному топіку/групі
        if message.chat.id != int(TELEGRAM_GROUP_ID):
            return
        
        # Переконуємося, що повідомлення знаходиться саме в необхідному топіку
        # Оновлена логіка: обробляємо ТІЛЬКИ повідомлення з правильним message_thread_id
        if message.message_thread_id != int(TELEGRAM_TOPIC_ID):
            logger.info(f"Повідомлення не в потрібному топіку. Очікуваний ID: {TELEGRAM_TOPIC_ID}, Отриманий ID: {message.message_thread_id}")
            return
            
        # Зберігаємо ID повідомлення для передачі скрипту
        message_id = message.message_id
        logger.info(f"Обробка повідомлення з ID: {message_id}")
        
        # Відправляємо лог у спеціальний чат для логів
        await context.bot.send_message(
            chat_id=TELEGRAM_LOG_CHAT_ID,
            text=f"📥 Отримано повідомлення в потрібному топіку. ID повідомлення: {message_id}. Починаю обробку..."
        )
        
        # Якщо повідомлення належить до медіа-групи, передаємо його до іншого обробника
        if message.media_group_id:
            await handle_media_group_message(update, context)
            return
            
        # Перевіряємо наявність файлів
        if not message.document:
            return
        
        # Отримати текст повідомлення як реліз-ноут
        release_notes = message.caption if message.caption else "Новий реліз"
        
        # Отримати версію з часової мітки у форматі YYYY.MM.DD-HH.MM
        version = datetime.now().strftime("%Y.%m.%d-%H.%M")
        
        # Список файлів для додавання до релізу та словник для швидкого пошуку за ім'ям
        files_to_add = []
        files_dict = {}
        
        # Перевіряємо документ
        file_name = message.document.file_name
        # Перевіряємо, чи це архів (.zip)
        if file_name.endswith('.zip'):
            # Завантажуємо файл або отримуємо інформацію про нього (залежно від налаштувань)
            file_info = await download_file(context.bot, message, file_name)
            if file_info:
                files_to_add.append(file_info)
                files_dict[file_name] = file_info
                
                # Повідомлення залежно від стану завантаження
                if ENABLE_FILE_DOWNLOAD:
                    await context.bot.send_message(
                        chat_id=TELEGRAM_LOG_CHAT_ID,
                        text=f"📦 Файл {file_name} успішно завантажено у тимчасовий файл"
                    )
        
        # Якщо завантаження вимкнено, виходимо після виведення атрибутів
        if not ENABLE_FILE_DOWNLOAD:
            logger.info("Завантаження файлів вимкнено. Зупиняємо обробку після виведення атрибутів.")
            await context.bot.send_message(
                chat_id=TELEGRAM_LOG_CHAT_ID,
                text="ℹ️ Завантаження файлів вимкнено. Зупиняємо обробку після виведення атрибутів."
            )
            return
        
        # Перевіряємо, чи всі необхідні файли є наявні
        missing_required_files = []
        for required_file in REQUIRED_FILES:
            if required_file not in files_dict:
                missing_required_files.append(required_file)
        
        if missing_required_files:
            await context.bot.send_message(
                chat_id=TELEGRAM_LOG_CHAT_ID,
                text=f"⚠️ У повідомленні відсутні деякі необхідні файли: {', '.join(missing_required_files)}. Спробую завантажити їх з попереднього релізу."
            )
            
            # Завантажуємо відсутні файли з усіх попередніх релізів
            previous_files = download_required_files_from_previous_releases()
            
            for req_file in missing_required_files:
                if req_file in previous_files:
                    file_info = previous_files[req_file]
                    files_to_add.append(file_info)
                    files_dict[req_file] = file_info
                    
                    await context.bot.send_message(
                        chat_id=TELEGRAM_LOG_CHAT_ID,
                        text=f"📥 Файл {req_file} успішно завантажено з попередніх релізів"
                    )
                else:
                    await context.bot.send_message(
                        chat_id=TELEGRAM_LOG_CHAT_ID,
                        text=f"❓ Не вдалося знайти файл {req_file} ні в повідомленні, ні в жодному з попередніх релізів"
                    )
        
        # Якщо знайдено файли для додавання до релізу
        if files_to_add:
            success = False
            release_url = None
            file_names_str = ", ".join([f"`{file_info['name']}`" for file_info in files_to_add])
            
            # Створюємо реліз на GitHub з файлами, якщо ця функція дозволена
            if ENABLE_GITHUB_RELEASE:
                success, release_url = create_github_release(version, release_notes, files_to_add)
                
                # Видаляємо всі тимчасові файли
                for file_info in files_to_add:
                    if os.path.exists(file_info["path"]) and file_info["path"] != "dummy_path":
                        os.unlink(file_info["path"])
                
                if success:
                    success_message = f"✅ Реліз v{version} успішно створено на GitHub!\n" + \
                                      f"📂 Додано файли: {file_names_str}\n" + \
                                      f"📎 {release_url}"
                else:
                    await context.bot.send_message(
                        chat_id=TELEGRAM_LOG_CHAT_ID,
                        text="❌ Не вдалося створити реліз на GitHub. Перевірте логи."
                    )
                    return
            else:
                # Якщо створення релізу вимкнено, просто повідомляємо про файли
                success_message = f"✅ Файли успішно отримано. Створення релізу на GitHub вимкнено.\n" + \
                                  f"📂 Оброблені файли: {file_names_str}"
                success = True
                
                # Видаляємо тимчасові файли
                for file_info in files_to_add:
                    if os.path.exists(file_info["path"]) and file_info["path"] != "dummy_path":
                        os.unlink(file_info["path"])
            
            # Запускаємо скрипт перевірки, якщо дозволено і обробка файлів була успішною
            checker_result = False
            if success and ENABLE_CHECKER_SCRIPT:
                # Передаємо ID повідомлення у скрипт
                checker_result = run_checker_script(message_id)
                
                # Додаємо інформацію про запуск скрипта перевірки
                if checker_result:
                    success_message += f"\n🔍 Запущено скрипт перевірки з ID повідомлення: {message_id}"
                else:
                    success_message += "\n⚠️ Не вдалося запустити скрипт перевірки"
            elif success and not ENABLE_CHECKER_SCRIPT:
                success_message += "\nℹ️ Запуск скрипта перевірки вимкнено в налаштуваннях"
            
            await context.bot.send_message(
                chat_id=TELEGRAM_LOG_CHAT_ID,
                text=success_message,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await context.bot.send_message(
                chat_id=TELEGRAM_LOG_CHAT_ID,
                text="ℹ️ Не знайдено архівів для додавання до релізу."
            )
    except Exception as e:
        error_message = f"❌ Сталася помилка при обробці повідомлення: {str(e)}"
        logger.error(error_message)
        await context.bot.send_message(chat_id=TELEGRAM_LOG_CHAT_ID, text=error_message)

async def handle_media_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробити повідомлення з медіа-групи."""
    try:
        message = update.effective_message
        media_group_id = message.media_group_id
        
        # Зберігаємо ID повідомлення для передачі скрипту
        message_id = message.message_id
        logger.info(f"Обробка повідомлення з медіа-групи, ID: {message_id}")
        
        # Перевірка, чи повідомлення в потрібному топіку/групі
        if message.chat.id != int(TELEGRAM_GROUP_ID):
            return
        
        # Переконуємося, що повідомлення знаходиться саме в необхідному топіку
        if message.message_thread_id != int(TELEGRAM_TOPIC_ID):
            logger.info(f"Повідомлення медіа-групи не в потрібному топіку. Очікуваний ID: {TELEGRAM_TOPIC_ID}, Отриманий ID: {message.message_thread_id}")
            return
        
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
        
        # Перевіряємо, чи є документ і чи це ZIP-файл
        if not message.document or not message.document.file_name.endswith('.zip'):
            logger.info(f"Повідомлення в медіа-групі {media_group_id} не містить ZIP-архів. Пропускаємо.")
            return
        
        # Повідомляємо про початок обробки медіа-групи
        await context.bot.send_message(
            chat_id=TELEGRAM_LOG_CHAT_ID,
            text=f"📥 Обробка медіа-групи {media_group_id}. ID повідомлення: {message_id}. Зачекайте, щоб отримати всі файли..."
        )
        
        # Чекаємо 2 секунди, щоб переконатися, що всі повідомлення в медіа-групі вже отримані
        await asyncio.sleep(2)
        
        # Готуємо дані для релізу
        release_notes = message.caption if message.caption else "Новий реліз"
        version = datetime.now().strftime("%Y.%m.%d-%H.%M")
        files_to_add = []
        files_dict = {}
        
        # Додаємо поточний файл
        file_info = await download_file(context.bot, message, message.document.file_name)
        if file_info:
            files_to_add.append(file_info)
            files_dict[message.document.file_name] = file_info
            
            # Виводимо повідомлення лише якщо завантаження увімкнене
            if ENABLE_FILE_DOWNLOAD:
                await context.bot.send_message(
                    chat_id=TELEGRAM_LOG_CHAT_ID,
                    text=f"📦 Файл {message.document.file_name} з медіа-групи завантажено у тимчасовий файл"
                )
        
        # Якщо завантаження вимкнено, виходимо після виведення атрибутів
        if not ENABLE_FILE_DOWNLOAD:
            logger.info("Завантаження файлів вимкнено. Зупиняємо обробку після виведення атрибутів.")
            await context.bot.send_message(
                chat_id=TELEGRAM_LOG_CHAT_ID,
                text="ℹ️ Завантаження файлів вимкнено. Зупиняємо обробку після виведення атрибутів."
            )
            return
        
        # Зберігаємо повідомлення з медіа-групи у контексті для подальшої обробки
        if not context.bot_data.get('media_groups'):
            context.bot_data['media_groups'] = {}
        
        if not context.bot_data['media_groups'].get(media_group_id):
            context.bot_data['media_groups'][media_group_id] = []
            
        # Додаємо поточне повідомлення до списку
        if message.document and message.document.file_name.endswith('.zip'):
            context.bot_data['media_groups'][media_group_id].append({
                'message': message,
                'file_name': message.document.file_name
            })
        
        # Перевіряємо, чи всі необхідні файли є наявні
        missing_required_files = []
        for required_file in REQUIRED_FILES:
            if required_file not in files_dict:
                missing_required_files.append(required_file)
        
        if missing_required_files:
            await context.bot.send_message(
                chat_id=TELEGRAM_LOG_CHAT_ID,
                text=f"⚠️ У медіа-групі відсутні деякі необхідні файли: {', '.join(missing_required_files)}. Спробую завантажити їх з попереднього релізу."
            )
            
            # Завантажуємо відсутні файли з усіх попередніх релізів
            previous_files = download_required_files_from_previous_releases()
            
            for req_file in missing_required_files:
                if req_file in previous_files:
                    file_info = previous_files[req_file]
                    files_to_add.append(file_info)
                    files_dict[req_file] = file_info
                    
                    await context.bot.send_message(
                        chat_id=TELEGRAM_LOG_CHAT_ID,
                        text=f"📥 Файл {req_file} успішно завантажено з попередніх релізів"
                    )
                else:
                    await context.bot.send_message(
                        chat_id=TELEGRAM_LOG_CHAT_ID,
                        text=f"❓ Не вдалося знайти файл {req_file} ні в медіа-групі, ні в жодному з попередніх релізів"
                    )
        
        # Якщо знайдено файли для додавання до релізу
        if files_to_add:
            success = False
            release_url = None
            file_names_str = ", ".join([f"`{file_info['name']}`" for file_info in files_to_add])
            
            # Створюємо реліз на GitHub з файлами, якщо ця функція дозволена
            if ENABLE_GITHUB_RELEASE:
                success, release_url = create_github_release(version, release_notes, files_to_add)
                
                # Видаляємо всі тимчасові файли
                for file_info in files_to_add:
                    if os.path.exists(file_info["path"]) and file_info["path"] != "dummy_path":
                        os.unlink(file_info["path"])
                
                if success:
                    success_message = f"✅ Реліз v{version} успішно створено на GitHub!\n" + \
                                      f"📂 Додано файли з медіа-групи: {file_names_str}\n" + \
                                      f"📎 {release_url}"
                else:
                    await context.bot.send_message(
                        chat_id=TELEGRAM_LOG_CHAT_ID,
                        text="❌ Не вдалося створити реліз на GitHub. Перевірте логи."
                    )
                    return
            else:
                # Якщо створення релізу вимкнено, просто повідомляємо про файли
                success_message = f"✅ Файли з медіа-групи успішно отримано. Створення релізу на GitHub вимкнено.\n" + \
                                  f"📂 Оброблені файли: {file_names_str}"
                success = True
                
                # Видаляємо тимчасові файли
                for file_info in files_to_add:
                    if os.path.exists(file_info["path"]) and file_info["path"] != "dummy_path":
                        os.unlink(file_info["path"])
            
            # Запускаємо скрипт перевірки, якщо дозволено і обробка файлів була успішною
            checker_result = False
            if success and ENABLE_CHECKER_SCRIPT:
                # Передаємо ID повідомлення у скрипт
                checker_result = run_checker_script(message_id)
                
                # Додаємо інформацію про запуск скрипта перевірки
                if checker_result:
                    success_message += f"\n🔍 Запущено скрипт перевірки з ID повідомлення: {message_id}"
                else:
                    success_message += "\n⚠️ Не вдалося запустити скрипт перевірки"
            elif success and not ENABLE_CHECKER_SCRIPT:
                success_message += "\nℹ️ Запуск скрипта перевірки вимкнено в налаштуваннях"
            
            await context.bot.send_message(
                chat_id=TELEGRAM_LOG_CHAT_ID,
                text=success_message,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await context.bot.send_message(
                chat_id=TELEGRAM_LOG_CHAT_ID,
                text="ℹ️ В медіа-групі не знайдено архівів для релізу."
            )
            
    except Exception as e:
        error_message = f"❌ Сталася помилка при обробці медіа-групи: {str(e)}"
        logger.error(error_message)
        await context.bot.send_message(chat_id=TELEGRAM_LOG_CHAT_ID, text=error_message)