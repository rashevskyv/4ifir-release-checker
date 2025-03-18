import asyncio
import os
from datetime import datetime, timedelta

from telethon import events
from telethon.tl.types import Message, MessageMediaDocument

from config import (
    TELEGRAM_GROUP_ID, TELEGRAM_TOPIC_ID, 
    TELEGRAM_LOG_CHAT_ID, REQUIRED_FILES, logger,
    ENABLE_GITHUB_RELEASE, ENABLE_CHECKER_SCRIPT
)
from github_api import (
    create_github_release, download_required_files_from_previous_releases
)
from utils import run_checker_script, download_and_save_file

# Словник для відстеження оброблених медіа-груп
processed_media_groups = {}

async def handle_document(event):
    """Обробити повідомлення з документом."""
    try:
        message = event.message
        
        # Перевірка, чи повідомлення в потрібному топіку
        if hasattr(message, 'reply_to') and message.reply_to and message.reply_to.reply_to_msg_id == TELEGRAM_TOPIC_ID:
            # Відправляємо лог у спеціальний чат для логів
            await event.client.send_message(
                TELEGRAM_LOG_CHAT_ID,
                f"📥 Отримано повідомлення в топіку {TELEGRAM_TOPIC_ID}. Починаю обробку..."
            )
        else:
            return
        
        # Якщо повідомлення належить до медіа-групи, передаємо його до іншого обробника
        if message.grouped_id:
            await handle_media_group_message(event.client, message)
            return
            
        # Перевіряємо наявність файлів
        if not message.file:
            return
        
        # Отримати текст повідомлення як реліз-ноут
        release_notes = message.message if message.message else "Новий реліз"
        
        # Отримати версію з часової мітки у форматі YYYY.MM.DD-HH.MM
        version = datetime.now().strftime("%Y.%m.%d-%H.%M")
        
        # Список файлів для додавання до релізу та словник для швидкого пошуку за ім'ям
        files_to_add = []
        files_dict = {}
        
        # Перевіряємо документ
        file_name = message.file.name
        # Перевіряємо, чи це архів (.zip)
        if file_name.endswith('.zip'):
            file_info = await download_and_save_file(event.client, message)
            if file_info:
                files_to_add.append(file_info)
                files_dict[file_name] = file_info
                
                await event.client.send_message(
                    TELEGRAM_LOG_CHAT_ID,
                    f"📦 Файл {file_name} успішно завантажено у тимчасовий файл"
                )
        
        # Перевіряємо, чи всі необхідні файли є наявні
        missing_required_files = []
        for required_file in REQUIRED_FILES:
            if required_file not in files_dict:
                missing_required_files.append(required_file)
        
        if missing_required_files:
            await event.client.send_message(
                TELEGRAM_LOG_CHAT_ID,
                f"⚠️ У повідомленні відсутні деякі необхідні файли: {', '.join(missing_required_files)}. Спробую завантажити їх з попереднього релізу."
            )
            
            # Завантажуємо відсутні файли з усіх попередніх релізів
            previous_files = download_required_files_from_previous_releases()
            
            for req_file in missing_required_files:
                if req_file in previous_files:
                    file_info = previous_files[req_file]
                    files_to_add.append(file_info)
                    files_dict[req_file] = file_info
                    
                    await event.client.send_message(
                        TELEGRAM_LOG_CHAT_ID,
                        f"📥 Файл {req_file} успішно завантажено з попередніх релізів"
                    )
                else:
                    await event.client.send_message(
                        TELEGRAM_LOG_CHAT_ID,
                        f"❓ Не вдалося знайти файл {req_file} ні в повідомленні, ні в жодному з попередніх релізів"
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
                    os.unlink(file_info["path"])
                
                if success:
                    success_message = f"✅ Реліз v{version} успішно створено на GitHub!\n" + \
                                      f"📂 Додано файли: {file_names_str}\n" + \
                                      f"📎 {release_url}"
                else:
                    await event.client.send_message(
                        TELEGRAM_LOG_CHAT_ID,
                        "❌ Не вдалося створити реліз на GitHub. Перевірте логи."
                    )
                    return
            else:
                # Якщо створення релізу вимкнено, просто повідомляємо про файли
                success_message = f"✅ Файли успішно отримано. Створення релізу на GitHub вимкнено.\n" + \
                                  f"📂 Оброблені файли: {file_names_str}"
                success = True
                
                # Видаляємо тимчасові файли
                for file_info in files_to_add:
                    os.unlink(file_info["path"])
            
            # Запускаємо скрипт перевірки, якщо дозволено і обробка файлів була успішною
            checker_result = False
            if success and ENABLE_CHECKER_SCRIPT:
                checker_result = run_checker_script()
                
                # Додаємо інформацію про запуск скрипта перевірки
                if checker_result:
                    success_message += "\n🔍 Запущено скрипт перевірки"
                else:
                    success_message += "\n⚠️ Не вдалося запустити скрипт перевірки"
            elif success and not ENABLE_CHECKER_SCRIPT:
                success_message += "\nℹ️ Запуск скрипта перевірки вимкнено в налаштуваннях"
            
            await event.client.send_message(
                TELEGRAM_LOG_CHAT_ID,
                success_message
            )
        else:
            await event.client.send_message(
                TELEGRAM_LOG_CHAT_ID,
                "ℹ️ Не знайдено архівів для додавання до релізу."
            )
    except Exception as e:
        error_message = f"❌ Сталася помилка при обробці повідомлення: {str(e)}"
        logger.error(error_message)
        await event.client.send_message(TELEGRAM_LOG_CHAT_ID, error_message)

async def handle_media_group_message(client, message):
    """Обробити повідомлення з медіа-групи."""
    try:
        media_group_id = message.grouped_id
        
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
        if not message.file or not message.file.name.endswith('.zip'):
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
        release_notes = message.message if message.message else "Новий реліз"
        version = datetime.now().strftime("%Y.%m.%d-%H.%M")
        files_to_add = []
        files_dict = {}
        
        # Додаємо поточний файл
        file_info = await download_and_save_file(client, message)
        if file_info:
            files_to_add.append(file_info)
            files_dict[message.file.name] = file_info
            
            await client.send_message(
                TELEGRAM_LOG_CHAT_ID,
                f"📦 Файл {message.file.name} з медіа-групи завантажено у тимчасовий файл"
            )
        
        # Отримуємо історію повідомлень з цієї медіа-групи (за останні кілька хвилин)
        five_minutes_ago = int((current_time - timedelta(minutes=5)).timestamp())
        
        try:
            async for msg in client.iter_messages(TELEGRAM_GROUP_ID, limit=50):
                # Шукаємо повідомлення з тією ж медіа-групою
                if (msg.grouped_id == media_group_id and 
                    msg.id != message.id and  # не дублюємо поточне повідомлення
                    msg.file and 
                    msg.file.name.endswith('.zip')):
                    
                    # Завантажуємо файл
                    additional_file_info = await download_and_save_file(client, msg)
                    if additional_file_info:
                        files_to_add.append(additional_file_info)
                        files_dict[msg.file.name] = additional_file_info
                        
                        await client.send_message(
                            TELEGRAM_LOG_CHAT_ID,
                            f"📦 Додатковий файл {msg.file.name} з медіа-групи завантажено у тимчасовий файл"
                        )
        except Exception as e:
            logger.error(f"Помилка при отриманні додаткових повідомлень медіа-групи: {e}")
        
        # Перевіряємо, чи всі необхідні файли є наявні
        missing_required_files = []
        for required_file in REQUIRED_FILES:
            if required_file not in files_dict:
                missing_required_files.append(required_file)
        
        if missing_required_files:
            await client.send_message(
                TELEGRAM_LOG_CHAT_ID,
                f"⚠️ У медіа-групі відсутні деякі необхідні файли: {', '.join(missing_required_files)}. Спробую завантажити їх з попереднього релізу."
            )
            
            # Завантажуємо відсутні файли з усіх попередніх релізів
            previous_files = download_required_files_from_previous_releases()
            
            for req_file in missing_required_files:
                if req_file in previous_files:
                    file_info = previous_files[req_file]
                    files_to_add.append(file_info)
                    files_dict[req_file] = file_info
                    
                    await client.send_message(
                        TELEGRAM_LOG_CHAT_ID,
                        f"📥 Файл {req_file} успішно завантажено з попередніх релізів"
                    )
                else:
                    await client.send_message(
                        TELEGRAM_LOG_CHAT_ID,
                        f"❓ Не вдалося знайти файл {req_file} ні в медіа-групі, ні в жодному з попередніх релізів"
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
                    os.unlink(file_info["path"])
                
                if success:
                    success_message = f"✅ Реліз v{version} успішно створено на GitHub!\n" + \
                                      f"📂 Додано файли з медіа-групи: {file_names_str}\n" + \
                                      f"📎 {release_url}"
                else:
                    await client.send_message(
                        TELEGRAM_LOG_CHAT_ID,
                        "❌ Не вдалося створити реліз на GitHub. Перевірте логи."
                    )
                    return
            else:
                # Якщо створення релізу вимкнено, просто повідомляємо про файли
                success_message = f"✅ Файли з медіа-групи успішно отримано. Створення релізу на GitHub вимкнено.\n" + \
                                  f"📂 Оброблені файли: {file_names_str}"
                success = True
                
                # Видаляємо тимчасові файли
                for file_info in files_to_add:
                    os.unlink(file_info["path"])
            
            # Запускаємо скрипт перевірки, якщо дозволено і обробка файлів була успішною
            checker_result = False
            if success and ENABLE_CHECKER_SCRIPT:
                checker_result = run_checker_script()
                
                # Додаємо інформацію про запуск скрипта перевірки
                if checker_result:
                    success_message += "\n🔍 Запущено скрипт перевірки"
                else:
                    success_message += "\n⚠️ Не вдалося запустити скрипт перевірки"
            elif success and not ENABLE_CHECKER_SCRIPT:
                success_message += "\nℹ️ Запуск скрипта перевірки вимкнено в налаштуваннях"
            
            await client.send_message(
                TELEGRAM_LOG_CHAT_ID,
                success_message
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