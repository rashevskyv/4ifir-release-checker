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

# --- ДОПОМІЖНІ ФУНКЦІЇ ---

def extract_release_notes(message):
    """
    Витягує текст для опису релізу.
    1. Reply (текст повідомлення, на яке відповіли).
    2. Caption (підпис до файлу).
    """
    if message.reply_to_message:
        reply = message.reply_to_message
        text = reply.text or reply.caption
        if text:
            return text
            
    if message.caption:
        return message.caption
        
    return None

# --- ЛОГІКА РЕЛІЗУ ---

async def process_release_logic(context: ContextTypes.DEFAULT_TYPE, telegram_files, release_notes, message_id):
    """
    Основна логіка: перевірка файлів -> GitHub -> Checker.
    """
    try:
        version = datetime.now().strftime("%Y.%m.%d-%H.%M")
        
        final_files_list = list(telegram_files)
        updated_names = [f["name"] for f in telegram_files]
        kept_names = []
        
        files_map = {f["name"]: f for f in final_files_list}
        
        # Перевірка на відсутні файли
        missing_required_files = []
        for required_file in REQUIRED_FILES:
            if required_file not in files_map:
                missing_required_files.append(required_file)
        
        # Докачування з історії
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
                        text=f"❌ Файл {req_file} не знайдено ніде!"
                    )

        if final_files_list:
            success = False
            release_url = None
            
            # Генерація опису
            description_parts = []
            
            if updated_names:
                description_parts.append("🆕 **Оновлено:**")
                for name in updated_names:
                    description_parts.append(f"- `{name}`")
            
            if kept_names:
                description_parts.append("\n♻️ **Без змін:**")
                for name in kept_names:
                    description_parts.append(f"- `{name}`")
            
            if release_notes and len(release_notes.strip()) > 0:
                description_parts.append(f"\n📝 **Список змін:**\n{release_notes}")
            
            full_description = "\n".join(description_parts)
            
            # GitHub Release
            if ENABLE_GITHUB_RELEASE:
                success, release_url = create_github_release(version, full_description, final_files_list)
                if success:
                    success_message = (
                        f"✅ **Реліз v{version} створено!**\n\n"
                        f"{full_description}\n\n"
                        f"📎 [GitHub Release]({release_url})"
                    )
                else:
                    await context.bot.send_message(chat_id=TELEGRAM_LOG_CHAT_ID, text="❌ Помилка GitHub API.")
                    return
            else:
                success_message = f"✅ Файли оброблено.\n\n{full_description}"
                success = True
            
            # Видалення файлів
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
                await context.bot.send_message(chat_id=TELEGRAM_LOG_CHAT_ID, text=success_message, parse_mode=ParseMode.MARKDOWN)
        else:
            await context.bot.send_message(chat_id=TELEGRAM_LOG_CHAT_ID, text="ℹ️ Немає файлів.")

    except Exception as e:
        logger.error(f"Logic Error: {e}")
        await context.bot.send_message(chat_id=TELEGRAM_LOG_CHAT_ID, text=f"❌ Error: {e}")

# --- БУФЕРИЗАЦІЯ ТА ОБРОБКА ---

async def process_buffered_files(context: ContextTypes.DEFAULT_TYPE, group_id: str):
    """
    Виконується, коли таймер очікування (4 с) сплив.
    Завантажує файли та запускає реліз.
    """
    if 'media_groups_buffer' not in context.bot_data: return
    if group_id not in context.bot_data['media_groups_buffer']: return
    
    group_data = context.bot_data['media_groups_buffer'][group_id]
    messages = group_data['messages']
    del context.bot_data['media_groups_buffer'][group_id] # Очищаємо буфер
    
    # Визначаємо основний меседж (перший)
    first_msg = messages[0]
    release_notes = extract_release_notes(first_msg)
    main_msg_id = first_msg.message_id
    
    # Лог
    count_str = f"{len(messages)} файлів" if len(messages) > 1 else "1 файл"
    await context.bot.send_message(
        chat_id=TELEGRAM_LOG_CHAT_ID,
        text=f"📥 Отримано {count_str}. Починаю завантаження..."
    )
    
    downloaded_files = []
    
    # Завантажуємо
    for msg in messages:
        file_name = msg.document.file_name
        try:
            file_info = await download_file(context.bot, msg, file_name)
            if file_info:
                downloaded_files.append(file_info)
        except Exception as e:
            logger.error(f"Download failed {file_name}: {e}")
            await context.bot.send_message(chat_id=TELEGRAM_LOG_CHAT_ID, text=f"⚠️ Помилка завантаження: {file_name}")

    if downloaded_files:
        await process_release_logic(context, downloaded_files, release_notes, main_msg_id)
    else:
        await context.bot.send_message(chat_id=TELEGRAM_LOG_CHAT_ID, text="❌ Жоден файл не завантажився.")

async def _wait_and_process(context, group_id):
    """Таймер очікування завершення групи."""
    try:
        await asyncio.sleep(4) 
        await process_buffered_files(context, group_id)
    except asyncio.CancelledError:
        pass 

async def buffer_document(update: Update, context: ContextTypes.DEFAULT_TYPE, group_id: str):
    """
    Додає файл у буфер. Якщо таймер існує — скидає його.
    """
    message = update.effective_message
    
    if 'media_groups_buffer' not in context.bot_data:
        context.bot_data['media_groups_buffer'] = {}
    
    buffer = context.bot_data['media_groups_buffer']

    if group_id not in buffer:
        buffer[group_id] = {
            'messages': [],
            'timer_task': None
        }
        logger.info(f"🆕 Старт буферизації: {group_id}")
    
    buffer[group_id]['messages'].append(message)

    # Перезапуск таймера (Debounce)
    if buffer[group_id]['timer_task']:
        buffer[group_id]['timer_task'].cancel()
    
    buffer[group_id]['timer_task'] = asyncio.create_task(
        _wait_and_process(context, group_id)
    )

# --- ГОЛОВНИЙ ОБРОБНИК ---

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Єдина точка входу.
    Приймає як одиночні файли, так і частини альбомів.
    Всіх відправляє в буфер.
    """
    message = update.effective_message
    
    # 1. Перевірки чату
    if message.chat.id != int(TELEGRAM_GROUP_ID): return
    if message.message_thread_id and message.message_thread_id != int(TELEGRAM_TOPIC_ID): return
    
    # 2. Перевірка файлу
    if not message.document: return
    file_name = message.document.file_name
    if not file_name or not file_name.lower().endswith('.zip'): return

    # 3. Визначення ID групи
    # Якщо це медіа-група — використовуємо її ID.
    # Якщо одиночний файл — генеруємо унікальний ID на основі message_id.
    if message.media_group_id:
        group_id = message.media_group_id
    else:
        # Префікс 'single_' щоб не перетиналося з реальними ID
        group_id = f"single_{message.message_id}"
    
    # 4. Відправка в буфер
    await buffer_document(update, context, group_id)