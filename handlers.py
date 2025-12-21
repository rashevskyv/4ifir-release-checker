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
from utils import run_checker_script_async, download_file

# --- ЛОГІКА ФОРМУВАННЯ РЕЛІЗУ ---

async def process_release_logic(context: ContextTypes.DEFAULT_TYPE, telegram_files, release_notes, message_id):
    """
    telegram_files: список файлів, які щойно завантажені з Telegram.
    """
    try:
        version = datetime.now().strftime("%Y.%m.%d-%H.%M")
        
        # Списки для звіту
        final_files_list = list(telegram_files)
        updated_names = [f["name"] for f in telegram_files]
        kept_names = []
        
        # Словник для швидкого пошуку
        files_map = {f["name"]: f for f in final_files_list}
        
        # 1. Перевіряємо, яких обов'язкових файлів не вистачає
        missing_required_files = []
        for required_file in REQUIRED_FILES:
            if required_file not in files_map:
                missing_required_files.append(required_file)
        
        # 2. Докачуємо відсутнє з історії (GitHub)
        if missing_required_files:
            # await context.bot.send_message(chat_id=TELEGRAM_LOG_CHAT_ID, text=f"🔍 Докачую з історії: {', '.join(missing_required_files)}...")
            previous_files = download_required_files_from_previous_releases()
            
            for req_file in missing_required_files:
                if req_file in previous_files:
                    file_info = previous_files[req_file]
                    final_files_list.append(file_info)
                    kept_names.append(req_file)
                else:
                    await context.bot.send_message(
                        chat_id=TELEGRAM_LOG_CHAT_ID,
                        text=f"❌ Файл {req_file} не знайдено ні в новому пості, ні в історії."
                    )

        if final_files_list:
            success = False
            release_url = None
            
            # --- ГЕНЕРАЦІЯ ОПИСУ ---
            description_parts = []
            
            if updated_names:
                description_parts.append("🆕 **Оновлено (з Telegram):**")
                for name in updated_names:
                    description_parts.append(f"- `{name}`")
            
            if kept_names:
                description_parts.append("\n♻️ **Без змін (з попередніх версій):**")
                for name in kept_names:
                    description_parts.append(f"- `{name}`")
            
            # Додаємо нотатки користувача, якщо вони є
            if release_notes and len(release_notes) > 0:
                description_parts.append(f"\n📝 **Нотатки:**\n{release_notes}")
            
            full_description = "\n".join(description_parts)
            
            # --- СТВОРЕННЯ РЕЛІЗУ НА GITHUB ---
            if ENABLE_GITHUB_RELEASE:
                success, release_url = create_github_release(version, full_description, final_files_list)
                
                if success:
                    success_message = (
                        f"✅ **Реліз v{version} створено!**\n\n"
                        f"{full_description}\n\n"
                        f"📎 [GitHub Release]({release_url})"
                    )
                else:
                    await context.bot.send_message(chat_id=TELEGRAM_LOG_CHAT_ID, text="❌ Помилка API GitHub.")
                    return
            else:
                success_message = f"✅ Файли оброблено (GitHub вимкнено).\n\n{full_description}"
                success = True
            
            # Видаляємо тимчасові файли
            for file_info in final_files_list:
                if os.path.exists(file_info["path"]) and "dummy" not in file_info["path"]:
                    try: os.unlink(file_info["path"])
                    except: pass

            # --- ЗАПУСК CHECKER ---
            if success and ENABLE_CHECKER_SCRIPT:
                await context.bot.send_message(
                    chat_id=TELEGRAM_LOG_CHAT_ID, 
                    text=success_message + "\n\n⏳ Запускаю скрипт перевірки...",
                    parse_mode=ParseMode.MARKDOWN
                )
                check_ok = await run_checker_script_async(message_id)
                res_txt = "✅ Перевірка успішна" if check_ok else "⚠️ Помилка перевірки"
                await context.bot.send_message(chat_id=TELEGRAM_LOG_CHAT_ID, text=res_txt)
            else:
                await context.bot.send_message(
                    chat_id=TELEGRAM_LOG_CHAT_ID,
                    text=success_message,
                    parse_mode=ParseMode.MARKDOWN
                )
        else:
            await context.bot.send_message(chat_id=TELEGRAM_LOG_CHAT_ID, text="ℹ️ Немає файлів для релізу.")

    except Exception as e:
        logger.error(f"Logic Error: {e}")
        await context.bot.send_message(chat_id=TELEGRAM_LOG_CHAT_ID, text=f"❌ Error: {e}")


# --- ОБРОБКА АЛЬБОМУ (КОЛЕКТОР) ---

async def process_album(context: ContextTypes.DEFAULT_TYPE, group_id: str):
    """
    Ця функція запускається, коли альбом повністю зібрано (таймер 4 сек вийшов).
    Тут ми вже знаємо кількість файлів і качаємо їх.
    """
    if 'media_groups_buffer' not in context.bot_data: return
    if group_id not in context.bot_data['media_groups_buffer']: return
    
    group_data = context.bot_data['media_groups_buffer'][group_id]
    
    # Витягуємо список повідомлень
    messages = group_data['messages']
    caption = group_data.get('caption', "")
    main_msg_id = group_data['main_msg_id']
    
    # Видаляємо з буфера, щоб не обробити двічі
    del context.bot_data['media_groups_buffer'][group_id]
    
    await context.bot.send_message(
        chat_id=TELEGRAM_LOG_CHAT_ID,
        text=f"📥 Альбом зібрано ({len(messages)} файлів). Починаю завантаження..."
    )
    
    downloaded_files = []
    
    # ЗАВАНТАЖУЄМО ВСІ ФАЙЛИ ПО ЧЕРЗІ
    for msg in messages:
        file_name = msg.document.file_name
        try:
            file_info = await download_file(context.bot, msg, file_name)
            if file_info:
                downloaded_files.append(file_info)
        except Exception as e:
            logger.error(f"Failed to download {file_name}: {e}")
            await context.bot.send_message(chat_id=TELEGRAM_LOG_CHAT_ID, text=f"⚠️ Не вдалося завантажити {file_name}")

    # Коли все завантажено - робимо реліз
    if downloaded_files:
        await process_release_logic(context, downloaded_files, caption, main_msg_id)
    else:
        await context.bot.send_message(chat_id=TELEGRAM_LOG_CHAT_ID, text="❌ Жоден файл з альбому не завантажився.")


async def handle_media_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Збирає повідомлення альбому в список.
    """
    message = update.effective_message
    group_id = message.media_group_id
    file_name = message.document.file_name

    if not file_name.endswith('.zip'): return

    if 'media_groups_buffer' not in context.bot_data:
        context.bot_data['media_groups_buffer'] = {}
    
    buffer = context.bot_data['media_groups_buffer']

    # Якщо це перший файл з групи
    if group_id not in buffer:
        buffer[group_id] = {
            'messages': [],
            'caption': None,
            'main_msg_id': message.message_id,
            'timer_task': None
        }
        logger.info(f"🆕 Нова група {group_id}, починаю збір...")
    
    group_data = buffer[group_id]
    
    # Додаємо повідомлення в список (НЕ качаємо ще)
    group_data['messages'].append(message)
    
    # Зберігаємо текст (шукаємо перший непорожній)
    if message.caption and not group_data['caption']:
        group_data['caption'] = message.caption

    # Скидаємо таймер збору
    if group_data['timer_task']:
        group_data['timer_task'].cancel()
    
    # Ставимо новий таймер на 4 секунди. 
    # Якщо за 4 сек нових повідомлень не буде - запускаємо process_album
    group_data['timer_task'] = asyncio.create_task(
        _wait_and_process(context, group_id)
    )

async def _wait_and_process(context, group_id):
    """Допоміжна функція очікування."""
    try:
        await asyncio.sleep(4) # Чекаємо поки Telegram дошле всі частини альбому
        await process_album(context, group_id)
    except asyncio.CancelledError:
        pass # Таймер скасовано, бо прийшов новий файл - це нормально

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Одиночний файл або група."""
    message = update.effective_message
    
    if message.chat.id != int(TELEGRAM_GROUP_ID): return
    if message.message_thread_id and message.message_thread_id != int(TELEGRAM_TOPIC_ID): return
    
    # Якщо група - віддаємо в колектор
    if message.media_group_id:
        await handle_media_group_message(update, context)
        return

    # Якщо одиночний
    file_name = message.document.file_name
    if not file_name.endswith('.zip'): return

    await context.bot.send_message(chat_id=TELEGRAM_LOG_CHAT_ID, text=f"📥 Одиночний файл: {file_name}")
    
    # Качаємо відразу
    files_to_add = []
    file_info = await download_file(context.bot, message, file_name)
    if file_info:
        files_to_add.append(file_info)
    
    caption = message.caption if message.caption else "Новий реліз"
    await process_release_logic(context, files_to_add, caption, message.message_id)