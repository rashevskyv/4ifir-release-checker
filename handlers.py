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

# --- НОВА ФУНКЦІЯ: ВИТЯГУВАННЯ ОПИСУ ---

def extract_release_notes(message):
    """
    Визначає текст для опису релізу.
    Пріоритет:
    1. Текст повідомлення, на яке відповіли (Reply).
    2. Підпис (Caption) до самого файлу.
    3. None (якщо нічого немає).
    """
    # 1. Перевіряємо, чи це Reply (відповідь на інше повідомлення)
    if message.reply_to_message:
        reply = message.reply_to_message
        # В оригінальному повідомленні може бути text (якщо це просто текст) 
        # або caption (якщо це медіа)
        text = reply.text or reply.caption
        if text:
            return text
            
    # 2. Якщо не Reply, беремо підпис поточного повідомлення
    if message.caption:
        return message.caption
        
    return None

# --- ЛОГІКА ФОРМУВАННЯ РЕЛІЗУ ---

async def process_release_logic(context: ContextTypes.DEFAULT_TYPE, telegram_files, release_notes, message_id):
    """
    Формує реліз, докачує файли та відправляє на GitHub.
    """
    try:
        version = datetime.now().strftime("%Y.%m.%d-%H.%M")
        
        # Списки файлів
        final_files_list = list(telegram_files)
        updated_names = [f["name"] for f in telegram_files]
        kept_names = []
        
        # Словник для перевірки
        files_map = {f["name"]: f for f in final_files_list}
        
        # 1. Перевірка обов'язкових файлів
        missing_required_files = []
        for required_file in REQUIRED_FILES:
            if required_file not in files_map:
                missing_required_files.append(required_file)
        
        # 2. Докачування з історії
        if missing_required_files:
            previous_files = download_required_files_from_previous_releases()
            
            for req_file in missing_required_files:
                if req_file in previous_files:
                    file_info = previous_files[req_file]
                    final_files_list.append(file_info)
                    kept_names.append(req_file)
                else:
                    await context.bot.send_message(
                        chat_id=TELEGRAM_LOG_CHAT_ID,
                        text=f"❌ Файл {req_file} втрачено! Немає ні в новому пості, ні в історії."
                    )

        if final_files_list:
            success = False
            release_url = None
            
            # --- ГЕНЕРАЦІЯ ОПИСУ (Markdown) ---
            description_parts = []
            
            if updated_names:
                description_parts.append("🆕 **Оновлено (з Telegram):**")
                for name in updated_names:
                    description_parts.append(f"- `{name}`")
            
            if kept_names:
                description_parts.append("\n♻️ **Без змін (з історії):**")
                for name in kept_names:
                    description_parts.append(f"- `{name}`")
            
            # Додаємо текст (з реплаю або кепшена)
            if release_notes and len(release_notes.strip()) > 0:
                description_parts.append(f"\n📝 **Список змін:**\n{release_notes}")
            
            full_description = "\n".join(description_parts)
            
            # --- СТВОРЕННЯ РЕЛІЗУ ---
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
            
            # Очистка
            for file_info in final_files_list:
                if os.path.exists(file_info["path"]) and "dummy" not in file_info["path"]:
                    try: os.unlink(file_info["path"])
                    except: pass

            # Запуск скрипта перевірки
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
    Запускається таймером, коли альбом зібрано.
    """
    if 'media_groups_buffer' not in context.bot_data: return
    if group_id not in context.bot_data['media_groups_buffer']: return
    
    group_data = context.bot_data['media_groups_buffer'][group_id]
    messages = group_data['messages']
    
    # Визначаємо головний меседж (перший)
    first_msg = messages[0]
    # Витягуємо опис (шукаємо reply або caption)
    release_notes = extract_release_notes(first_msg)
    main_msg_id = first_msg.message_id
    
    # Чистимо буфер
    del context.bot_data['media_groups_buffer'][group_id]
    
    await context.bot.send_message(
        chat_id=TELEGRAM_LOG_CHAT_ID,
        text=f"📥 Альбом зібрано ({len(messages)} файлів). Починаю завантаження..."
    )
    
    downloaded_files = []
    
    for msg in messages:
        file_name = msg.document.file_name
        try:
            file_info = await download_file(context.bot, msg, file_name)
            if file_info:
                downloaded_files.append(file_info)
        except Exception as e:
            logger.error(f"Download failed {file_name}: {e}")
            await context.bot.send_message(chat_id=TELEGRAM_LOG_CHAT_ID, text=f"⚠️ Помилка: {file_name}")

    if downloaded_files:
        await process_release_logic(context, downloaded_files, release_notes, main_msg_id)
    else:
        await context.bot.send_message(chat_id=TELEGRAM_LOG_CHAT_ID, text="❌ Помилка: файли не завантажились.")


async def handle_media_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Тільки буферизує повідомлення. Стара логіка caption видалена.
    """
    message = update.effective_message
    group_id = message.media_group_id
    file_name = message.document.file_name

    if not file_name.endswith('.zip'): return

    if 'media_groups_buffer' not in context.bot_data:
        context.bot_data['media_groups_buffer'] = {}
    
    buffer = context.bot_data['media_groups_buffer']

    if group_id not in buffer:
        buffer[group_id] = {
            'messages': [],
            'timer_task': None
        }
        logger.info(f"🆕 Початок збору групи {group_id}")
    
    # Просто додаємо повідомлення в список
    buffer[group_id]['messages'].append(message)

    # Скидаємо/Заводимо таймер
    if buffer[group_id]['timer_task']:
        buffer[group_id]['timer_task'].cancel()
    
    buffer[group_id]['timer_task'] = asyncio.create_task(
        _wait_and_process(context, group_id)
    )

async def _wait_and_process(context, group_id):
    try:
        await asyncio.sleep(4) # Чекаємо завершення альбому
        await process_album(context, group_id)
    except asyncio.CancelledError:
        pass 

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Одиночний файл."""
    message = update.effective_message
    
    if message.chat.id != int(TELEGRAM_GROUP_ID): return
    if message.message_thread_id and message.message_thread_id != int(TELEGRAM_TOPIC_ID): return
    
    if message.media_group_id:
        await handle_media_group_message(update, context)
        return

    file_name = message.document.file_name
    if not file_name.endswith('.zip'): return

    await context.bot.send_message(chat_id=TELEGRAM_LOG_CHAT_ID, text=f"📥 Одиночний файл: {file_name}")
    
    files_to_add = []
    file_info = await download_file(context.bot, message, file_name)
    if file_info:
        files_to_add.append(file_info)
    
    # Використовуємо нову функцію
    release_notes = extract_release_notes(message)
    
    await process_release_logic(context, files_to_add, release_notes, message.message_id)