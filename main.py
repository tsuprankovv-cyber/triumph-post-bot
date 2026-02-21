import os
import logging
import json
import sqlite3
import random
import string
import re
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.enums import ParseMode

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Токен бота
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("❌ Нет токена! Добавь BOT_TOKEN в переменные окружения")

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ==================== БАЗА ДАННЫХ ====================

def init_db():
    conn = sqlite3.connect('templates.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS templates
                 (id TEXT PRIMARY KEY,
                  user_id INTEGER,
                  title TEXT,
                  content TEXT,
                  buttons TEXT,
                  media_type TEXT,
                  media_id TEXT,
                  created_at TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS saved_buttons
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  button_text TEXT,
                  button_url TEXT,
                  created_at TIMESTAMP)''')
    conn.commit()
    conn.close()

init_db()

# ==================== FSM СОСТОЯНИЯ ====================

class PostForm(StatesGroup):
    waiting_for_content = State()
    waiting_for_buttons = State()
    editing_buttons = State()

# ==================== ФУНКЦИИ ДЛЯ РАБОТЫ С БАЗОЙ ====================

def generate_key() -> str:
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=8))

def save_template(user_id: int, title: str, content: str, buttons: list, media_type: str = None, media_id: str = None) -> str:
    key = generate_key()
    conn = sqlite3.connect('templates.db')
    c = conn.cursor()
    c.execute('''INSERT INTO templates (id, user_id, title, content, buttons, media_type, media_id, created_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
              (key, user_id, title, content, json.dumps(buttons), media_type, media_id, datetime.now()))
    conn.commit()
    conn.close()
    return key

def get_template(key: str) -> dict | None:
    conn = sqlite3.connect('templates.db')
    c = conn.cursor()
    c.execute('SELECT * FROM templates WHERE id = ?', (key,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            'id': row[0],
            'user_id': row[1],
            'title': row[2],
            'content': row[3],
            'buttons': json.loads(row[4]) if row[4] else [],
            'media_type': row[5],
            'media_id': row[6]
        }
    return None

def get_user_templates(user_id: int) -> list:
    conn = sqlite3.connect('templates.db')
    c = conn.cursor()
    c.execute('''SELECT id, title, created_at FROM templates 
                 WHERE user_id = ? ORDER BY created_at DESC LIMIT 20''', (user_id,))
    rows = c.fetchall()
    conn.close()
    return [{'id': r[0], 'title': r[1]} for r in rows]

def save_button(user_id: int, text: str, url: str):
    conn = sqlite3.connect('templates.db')
    c = conn.cursor()
    c.execute('''INSERT INTO saved_buttons (user_id, button_text, button_url, created_at)
                 VALUES (?, ?, ?, ?)''', (user_id, text, url, datetime.now()))
    conn.commit()
    conn.close()

def get_saved_buttons(user_id: int) -> list:
    conn = sqlite3.connect('templates.db')
    c = conn.cursor()
    c.execute('''SELECT button_text, button_url FROM saved_buttons 
                 WHERE user_id = ? ORDER BY created_at DESC LIMIT 10''', (user_id,))
    rows = c.fetchall()
    conn.close()
    return [{'text': r[0], 'url': r[1]} for r in rows]

# ==================== КЛАВИАТУРЫ ====================

def main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="➕ Новый пост")
    builder.button(text="📋 Мои посты")
    builder.button(text="📚 Мои кнопки")
    builder.button(text="❓ Помощь")
    builder.adjust(2, 2)
    return builder.as_markup(resize_keyboard=True, input_field_placeholder="Выбери действие...")

def cancel_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="❌ Отмена")
    return builder.as_markup(resize_keyboard=True)

def buttons_action_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="➕ Добавить кнопки")
    builder.button(text="✅ Готово")
    builder.button(text="❌ Отмена")
    builder.adjust(2, 1)
    return builder.as_markup(resize_keyboard=True)

# ==================== ОБРАБОТЧИКИ КОМАНД ====================

@dp.message(Command('start'))
async def cmd_start(message: types.Message):
    await message.answer(
        "🤖 **Генератор постов**\n\n"
        "🔹 **➕ Новый пост** — создать пост с кнопками\n"
        "🔹 **📋 Мои посты** — список сохраненных\n"
        "🔹 **📚 Мои кнопки** — часто используемые\n"
        "🔹 **❓ Помощь** — подсказки",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_keyboard()
    )

@dp.message(F.text == "➕ Новый пост")
@dp.message(Command('new'))
async def cmd_new(message: types.Message, state: FSMContext):
    await state.set_state(PostForm.waiting_for_content)
    await message.answer(
        "📝 **Создание поста**\n\n"
        "Отправь **текст**, **фото** или **видео**.\n\n"
        "Можно использовать:\n"
        "• **жирный**, *курсив*, `код`\n"
        "• 😊 эмодзи\n"
        "• [ссылки](https://example.com)",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=cancel_keyboard()
    )

@dp.message(F.text == "📋 Мои посты")
async def cmd_list(message: types.Message):
    templates = get_user_templates(message.from_user.id)
    if not templates:
        await message.answer(
            "📭 У тебя пока нет сохраненных постов.\n"
            "Нажми **➕ Новый пост** чтобы создать первый!",
            reply_markup=main_keyboard()
        )
        return
    
    text = "**📋 Твои последние посты:**\n\n"
    for t in templates:
        text += f"🔹 `{t['id']}` — {t['title']}\n"
    
    text += "\nЧтобы опубликовать, введи в группе:\n`@твой_бот КЛЮЧ`"
    await message.answer(text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_keyboard())

@dp.message(F.text == "📚 Мои кнопки")
async def cmd_my_buttons(message: types.Message):
    buttons = get_saved_buttons(message.from_user.id)
    if not buttons:
        await message.answer(
            "📚 У тебя пока нет сохраненных кнопок.\n"
            "Они будут добавляться автоматически при создании постов.",
            reply_markup=main_keyboard()
        )
        return
    
    text = "**📚 Твои сохраненные кнопки:**\n\n"
    for i, btn in enumerate(buttons, 1):
        text += f"{i}. **{btn['text']}** — {btn['url']}\n"
    
    await message.answer(text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_keyboard())

@dp.message(F.text == "❓ Помощь")
async def cmd_help(message: types.Message):
    await message.answer(
        "**📖 Помощь**\n\n"
        "**Как создать пост:**\n"
        "1. Нажми **➕ Новый пост**\n"
        "2. Отправь текст/фото/видео\n"
        "3. Нажми **➕ Добавить кнопки**\n"
        "4. Введи кнопки в формате:\n"
        "   `Текст - ссылка`\n"
        "   или `Кнопка1 - url1 | Кнопка2 - url2`\n"
        "5. Нажми **✅ Готово**\n\n"
        "**Как опубликовать:**\n"
        "В группе введи: `@твой_бот КЛЮЧ`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_keyboard()
    )

@dp.message(F.text == "❌ Отмена")
@dp.message(Command('cancel'))
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Действие отменено", reply_markup=main_keyboard())

# ==================== ШАГ 1: ПОЛУЧЕНИЕ КОНТЕНТА ====================

@dp.message(PostForm.waiting_for_content)
async def handle_post_content(message: types.Message, state: FSMContext):
    content_data = {
        'text': message.html_text or message.caption or '',
        'media_type': None,
        'media_id': None
    }
    
    if message.photo:
        content_data['media_type'] = 'photo'
        content_data['media_id'] = message.photo[-1].file_id
        await message.answer("📸 **Фото получено!**\n\nНажми **➕ Добавить кнопки**", 
                           parse_mode=ParseMode.MARKDOWN, reply_markup=buttons_action_keyboard())
    elif message.video:
        content_data['media_type'] = 'video'
        content_data['media_id'] = message.video.file_id
        await message.answer("🎬 **Видео получено!**\n\nНажми **➕ Добавить кнопки**", 
                           parse_mode=ParseMode.MARKDOWN, reply_markup=buttons_action_keyboard())
    elif message.text:
        await message.answer("✍️ **Текст получен!**\n\nНажми **➕ Добавить кнопки**", 
                           parse_mode=ParseMode.MARKDOWN, reply_markup=buttons_action_keyboard())
    else:
        await message.answer("❌ Неподдерживаемый формат. Отправь текст, фото или видео.")
        return
    
    await state.update_data(content_data)
    await state.set_state(PostForm.waiting_for_buttons)

# ==================== ШАГ 2: ДОБАВЛЕНИЕ КНОПОК ====================

@dp.message(PostForm.waiting_for_buttons, F.text == "➕ Добавить кнопки")
async def ask_for_buttons(message: types.Message, state: FSMContext):
    await message.answer(
        "🔘 **Добавление кнопок**\n\n"
        "**Форматы:**\n"
        "• `Текст - ссылка` — одна кнопка\n"
        "• `Кнопка1 - url1 | Кнопка2 - url2` — две в ряд\n"
        "• Каждая новая строка = новая строка кнопок\n\n"
        "**Пример:**\n"
        "```\n"
        "Подобрать тур - https://vCard.guru/olga.tsuprankova\n"
        "Забронировать - https://booking.com | Отзывы - https://t.me/reviews\n"
        "```",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=buttons_action_keyboard()
    )

@dp.message(PostForm.waiting_for_buttons, F.text)
async def handle_buttons_input(message: types.Message, state: FSMContext):
    text = message.text
    
    if text == "✅ Готово":
        await finish_post(message, state)
        return
    
    if text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Создание поста отменено", reply_markup=main_keyboard())
        return
    
    # Парсинг кнопок
    lines = text.strip().split('\n')
    all_buttons = []
    
    for line in lines:
        if '|' in line:
            # Несколько кнопок в одной строке (горизонтально)
            buttons_in_row = line.split('|')
            row = []
            for btn_text in buttons_in_row:
                parts = re.split(r'\s*[-|]\s*', btn_text.strip(), maxsplit=1)
                if len(parts) == 2:
                    btn_name, btn_url = parts
                    if btn_url.startswith(('http://', 'https://', 'tg://', 't.me/')):
                        if btn_url.startswith('t.me/'):
                            btn_url = 'https://' + btn_url
                        row.append({'text': btn_name.strip(), 'url': btn_url.strip()})
                        save_button(message.from_user.id, btn_name.strip(), btn_url.strip())
            if row:
                all_buttons.append(row)
        else:
            # Одна кнопка
            parts = re.split(r'\s*[-|]\s*', line.strip(), maxsplit=1)
            if len(parts) == 2:
                btn_name, btn_url = parts
                if btn_url.startswith(('http://', 'https://', 'tg://', 't.me/')):
                    if btn_url.startswith('t.me/'):
                        btn_url = 'https://' + btn_url
                    all_buttons.append([{'text': btn_name.strip(), 'url': btn_url.strip()}])
                    save_button(message.from_user.id, btn_name.strip(), btn_url.strip())
    
    if all_buttons:
        # Получаем текущие кнопки из состояния и добавляем новые
        data = await state.get_data()
        existing_buttons = data.get('buttons', [])
        existing_buttons.extend(all_buttons)
        await state.update_data(buttons=existing_buttons)
        
        # Показываем предпросмотр
        await show_preview(message, state)
        
        await message.answer(
            "✅ Кнопки добавлены!\n"
            "Можешь добавить еще или нажать **✅ Готово**",
            reply_markup=buttons_action_keyboard()
        )
    else:
        await message.answer(
            "❌ Не удалось распознать кнопки.\n"
            "Используй формат: `Текст - ссылка`",
            parse_mode=ParseMode.MARKDOWN
        )

async def show_preview(message: types.Message, state: FSMContext):
    """Показывает полный предпросмотр поста без лишних надписей"""
    data = await state.get_data()
    content_text = data.get('text', '')
    media_type = data.get('media_type')
    media_id = data.get('media_id')
    buttons = data.get('buttons', [])
    
    # Создаем клавиатуру из кнопок
    kb = None
    if buttons:
        builder = InlineKeyboardBuilder()
        for row in buttons:
            for btn in row:
                builder.button(text=btn['text'], url=btn['url'])
        builder.adjust(1)
        kb = builder.as_markup()
    
    # Отправляем предпросмотр (только контент пользователя, без служебных фраз)
    if media_type == 'photo' and media_id:
        await message.answer_photo(
            photo=media_id, 
            caption=content_text if content_text else None, 
            reply_markup=kb, 
            parse_mode=ParseMode.MARKDOWN
        )
    elif media_type == 'video' and media_id:
        await message.answer_video(
            video=media_id, 
            caption=content_text if content_text else None, 
            reply_markup=kb, 
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        if content_text:
            await message.answer(content_text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        elif buttons:
            await message.answer(" ", reply_markup=kb)

# ==================== ЗАВЕРШЕНИЕ ПОСТА ====================

async def finish_post(message: types.Message, state: FSMContext):
    data = await state.get_data()
    content_text = data.get('text', '')
    media_type = data.get('media_type')
    media_id = data.get('media_id')
    buttons = data.get('buttons', [])
    
    # Создаем заголовок для списка
    if content_text:
        title = (content_text[:30] + '...') if len(content_text) > 30 else content_text
    else:
        title = f"{media_type} пост" if media_type else "Пост без текста"
    
    # Сохраняем в базу
    key = save_template(
        user_id=message.from_user.id,
        title=title,
        content=content_text,
        buttons=buttons,
        media_type=media_type,
        media_id=media_id
    )
    
    # Показываем финальный предпросмотр (только контент пользователя)
    kb = None
    if buttons:
        builder = InlineKeyboardBuilder()
        for row in buttons:
            for btn in row:
                builder.button(text=btn['text'], url=btn['url'])
        builder.adjust(1)
        kb = builder.as_markup()
    
    if media_type == 'photo' and media_id:
        await message.answer_photo(
            photo=media_id, 
            caption=content_text if content_text else None, 
            reply_markup=kb, 
            parse_mode=ParseMode.MARKDOWN
        )
    elif media_type == 'video' and media_id:
        await message.answer_video(
            video=media_id, 
            caption=content_text if content_text else None, 
            reply_markup=kb, 
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        if content_text:
            await message.answer(content_text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        elif buttons:
            await message.answer(" ", reply_markup=kb)
    
    # Отправляем ключ отдельным сообщением
    await message.answer(
        f"✅ **Пост готов!**\n\n"
        f"**Ключ:** `{key}`\n\n"
        f"📋 **Как опубликовать:**\n"
        f"Введи в группе:\n"
        f"`@{message.bot.username} {key}`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_keyboard()
    )
    
    await state.clear()

# ==================== INLINE РЕЖИМ ====================

@dp.inline_query()
async def inline_query_handler(query: InlineQuery):
    key = query.query.strip()
    
    if not key:
        templates = get_user_templates(query.from_user.id)
        results = []
        if templates:
            for t in templates[:10]:
                results.append(
                    InlineQueryResultArticle(
                        id=t['id'],
                        title=f'📄 {t["title"]}',
                        description=f'Ключ: {t["id"]}',
                        input_message_content=InputTextMessageContent(
                            message_text=f'Пост с ключом {t["id"]}',
                            parse_mode=ParseMode.MARKDOWN
                        )
                    )
                )
        else:
            results.append(
                InlineQueryResultArticle(
                    id='help',
                    title='📝 Введи ключ поста',
                    description='Например: ABC123',
                    input_message_content=InputTextMessageContent(
                        message_text='Введи ключ поста, например: `@твой_бот ABC123`',
                        parse_mode=ParseMode.MARKDOWN
                    )
                )
            )
        await query.answer(results, cache_time=1)
        return
    
    template = get_template(key)
    if not template:
        results = [InlineQueryResultArticle(
            id='not_found',
            title='❌ Пост не найден',
            description=f'Ключ "{key}" не существует',
            input_message_content=InputTextMessageContent(
                message_text=f'❌ Пост с ключом "{key}" не найден.'
            )
        )]
        await query.answer(results, cache_time=1)
        return
    
    # Создаем клавиатуру для inline-режима
    reply_markup = None
    if template['buttons']:
        builder = InlineKeyboardBuilder()
        for row in template['buttons']:
            for btn in row:
                builder.button(text=btn['text'], url=btn['url'])
        builder.adjust(1)
        reply_markup = builder.as_markup()
    
    # Создаем контент для публикации
    if template['media_type'] == 'photo' and template['media_id']:
        # Для фото нужна специальная обработка в inline-режиме
        # Пока возвращаем текст
        input_content = InputTextMessageContent(
            message_text=template['content'] or " ",
            parse_mode=ParseMode.MARKDOWN
        )
    elif template['media_type'] == 'video' and template['media_id']:
        input_content = InputTextMessageContent(
            message_text=template['content'] or " ",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        input_content = InputTextMessageContent(
            message_text=template['content'] or " ",
            parse_mode=ParseMode.MARKDOWN
        )
    
    results = [InlineQueryResultArticle(
        id=key,
        title=f'📄 {template["title"]}',
        description='Нажми, чтобы отправить',
        input_message_content=input_content,
        reply_markup=reply_markup
    )]
    
    await query.answer(results, cache_time=1)

# ==================== УДАЛЕНИЕ ПОСТОВ ====================

@dp.message(Command('delete'))
async def cmd_delete(message: types.Message):
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("❌ Укажи ключ: `/delete ABC123`", parse_mode=ParseMode.MARKDOWN)
        return
    
    key = parts[1]
    conn = sqlite3.connect('templates.db')
    c = conn.cursor()
    c.execute('DELETE FROM templates WHERE id = ? AND user_id = ?', (key, message.from_user.id))
    deleted = c.rowcount > 0
    conn.commit()
    conn.close()
    
    if deleted:
        await message.answer(f"✅ Пост `{key}` удален.", parse_mode=ParseMode.MARKDOWN)
    else:
        await message.answer(f"❌ Пост `{key}` не найден.", parse_mode=ParseMode.MARKDOWN)

# ==================== ЗАПУСК ====================

async def main():
    logger.info("🚀 Бот-генератор запускается...")
    await bot.delete_webhook()
    await dp.start_polling(bot)

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
