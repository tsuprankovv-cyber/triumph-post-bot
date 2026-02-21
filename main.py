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

# Токен бота из переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Инициализация базы данных
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
    conn.commit()
    conn.close()

init_db()

# Машина состояний для создания поста
class PostForm(StatesGroup):
    waiting_for_content = State()
    waiting_for_buttons = State()

def generate_key() -> str:
    """Генерирует короткий ключ для шаблона"""
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=8))

def save_template(user_id: int, title: str, content: str, buttons: list, media_type: str = None, media_id: str = None) -> str:
    """Сохраняет шаблон в базу"""
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
    """Получает шаблон по ключу"""
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
    """Возвращает список шаблонов пользователя"""
    conn = sqlite3.connect('templates.db')
    c = conn.cursor()
    c.execute('''SELECT id, title, created_at FROM templates 
                 WHERE user_id = ? ORDER BY created_at DESC LIMIT 20''', (user_id,))
    rows = c.fetchall()
    conn.close()
    return [{'id': r[0], 'title': r[1]} for r in rows]

def main_keyboard():
    """Главная клавиатура с кнопками"""
    builder = ReplyKeyboardBuilder()
    builder.button(text="➕ Новый пост")
    builder.button(text="📋 Мои посты")
    builder.button(text="❓ Помощь")
    builder.adjust(2, 1)
    return builder.as_markup(resize_keyboard=True)

def cancel_keyboard():
    """Клавиатура с кнопкой отмены"""
    builder = ReplyKeyboardBuilder()
    builder.button(text="❌ Отмена")
    return builder.as_markup(resize_keyboard=True)

@dp.message(Command('start'))
async def cmd_start(message: types.Message):
    """Приветствие с главной клавиатурой"""
    await message.answer(
        "🤖 **Генератор постов**\n\n"
        "Я помогаю создавать красивые посты с кнопками!\n\n"
        "**Что умею:**\n"
        "• Текст с форматированием\n"
        "• Эмодзи и смайлики\n"
        "• Кнопки-ссылки\n"
        "• Фото и видео\n\n"
        "Нажми **➕ Новый пост** чтобы начать",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_keyboard()
    )

@dp.message(F.text == "➕ Новый пост")
@dp.message(Command('new'))
async def cmd_new(message: types.Message, state: FSMContext):
    """Начало создания нового поста"""
    await state.set_state(PostForm.waiting_for_content)
    await message.answer(
        "📝 **Создание нового поста**\n\n"
        "Отправь мне **текст поста**.\n"
        "Можно использовать:\n"
        "• **жирный текст**\n"
        "• *курсив*\n"
        "• `код`\n"
        "• [ссылки](https://example.com)\n"
        "• 😊 эмодзи\n\n"
        "Если хочешь добавить фото или видео — просто прикрепи их к сообщению.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=cancel_keyboard()
    )

@dp.message(F.text == "📋 Мои посты")
@dp.message(Command('list'))
async def cmd_list(message: types.Message):
    """Показывает список сохраненных постов"""
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
    
    text += "\nЧтобы использовать пост, введи в группе:\n`@твой_бот КЛЮЧ`"
    
    await message.answer(text, parse_mode=ParseMode.MARKDOWN, reply_markup=main_keyboard())

@dp.message(F.text == "❓ Помощь")
@dp.message(Command('help'))
async def cmd_help(message: types.Message):
    """Справка"""
    await message.answer(
        "**📖 Помощь**\n\n"
        "**Как создать пост:**\n"
        "1. Нажми **➕ Новый пост**\n"
        "2. Отправь текст (можно с фото/видео)\n"
        "3. Добавь кнопки в формате:\n"
        "   `[Текст кнопки | https://ссылка.ru]`\n"
        "4. Получи ключ\n\n"
        "**Как опубликовать:**\n"
        "В группе введи: `@твой_бот КЛЮЧ`\n\n"
        "**Как удалить пост:**\n"
        "Введи команду: `/delete КЛЮЧ`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_keyboard()
    )

@dp.message(F.text == "❌ Отмена")
async def cmd_cancel(message: types.Message, state: FSMContext):
    """Отмена создания поста"""
    await state.clear()
    await message.answer(
        "❌ Создание поста отменено",
        reply_markup=main_keyboard()
    )

@dp.message(PostForm.waiting_for_content, F.content_type.in_({'text', 'photo', 'video'}))
async def handle_post_content(message: types.Message, state: FSMContext):
    """Обрабатывает полученный контент поста"""
    
    content_data = {
        'text': message.html_text or message.caption or '',
        'media_type': None,
        'media_id': None,
        'message': message
    }
    
    # Определяем тип медиа
    if message.photo:
        content_data['media_type'] = 'photo'
        content_data['media_id'] = message.photo[-1].file_id
        await message.answer("📸 Фото получено. Теперь добавь кнопки (или отправь /skip если не нужны)")
    elif message.video:
        content_data['media_type'] = 'video'
        content_data['media_id'] = message.video.file_id
        await message.answer("🎬 Видео получено. Теперь добавь кнопки (или отправь /skip если не нужны)")
    else:
        await message.answer("✍️ Текст получен. Теперь добавь кнопки (или отправь /skip если не нужны)")
    
    # Сохраняем данные в состоянии
    await state.update_data(content_data)
    await state.set_state(PostForm.waiting_for_buttons)

@dp.message(PostForm.waiting_for_buttons, F.text)
async def handle_buttons(message: types.Message, state: FSMContext):
    """Обрабатывает кнопки"""
    
    text = message.text
    
    if text == '/skip' or text == '❌ Пропустить':
        buttons = []
        await finish_post(message, state, buttons)
        return
    
    # Парсим кнопки из текста
    button_pattern = r'\[(.*?)\s*\|\s*(https?://[^\]]+)\]'
    buttons = []
    
    for match in re.finditer(button_pattern, text):
        button_text = match.group(1).strip()
        button_url = match.group(2).strip()
        buttons.append([{
            'text': button_text,
            'url': button_url
        }])
    
    if buttons:
        await finish_post(message, state, buttons)
    else:
        await message.answer(
            "❌ Не удалось распознать кнопки. Используй формат:\n"
            "`[Текст кнопки | https://ссылка.ru]`\n\n"
            "Или отправь /skip чтобы пропустить",
            parse_mode=ParseMode.MARKDOWN
        )

async def finish_post(message: types.Message, state: FSMContext, buttons: list):
    """Завершает создание поста и сохраняет его"""
    
    data = await state.get_data()
    content_text = data.get('text', '')
    media_type = data.get('media_type')
    media_id = data.get('media_id')
    
    # Создаем заголовок для списка
    title = (content_text[:30] + '...') if len(content_text) > 30 else (content_text or 'Пост без текста')
    
    # Сохраняем в базу
    key = save_template(
        user_id=message.from_user.id,
        title=title,
        content=content_text,
        buttons=buttons,
        media_type=media_type,
        media_id=media_id
    )
    
    # Показываем предпросмотр
    kb = None
    if buttons:
        builder = InlineKeyboardBuilder()
        for row in buttons:
            for btn in row:
                builder.button(text=btn['text'], url=btn['url'])
        builder.adjust(1)
        kb = builder.as_markup()
    
    preview_text = f"**Предпросмотр поста:**\n\n{content_text}"
    
    if media_type == 'photo' and media_id:
        await message.answer_photo(photo=media_id, caption=preview_text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
    elif media_type == 'video' and media_id:
        await message.answer_video(video=media_id, caption=preview_text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
    else:
        await message.answer(preview_text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
    
    # Отправляем ключ
    await message.answer(
        f"✅ **Пост сохранен!**\n\n"
        f"**Ключ:** `{key}`\n\n"
        f"Чтобы опубликовать, введи в группе:\n"
        f"`@{message.bot.username} {key}`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_keyboard()
    )
    
    await state.clear()

@dp.message(Command('delete'))
async def cmd_delete(message: types.Message):
    """Удаляет пост по ключу"""
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer(
            "❌ Укажи ключ: `/delete ABC123`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    key = parts[1]
    conn = sqlite3.connect('templates.db')
    c = conn.cursor()
    c.execute('DELETE FROM templates WHERE id = ? AND user_id = ?', 
              (key, message.from_user.id))
    deleted = c.rowcount > 0
    conn.commit()
    conn.close()
    
    if deleted:
        await message.answer(f"✅ Пост `{key}` удален.", parse_mode=ParseMode.MARKDOWN)
    else:
        await message.answer(f"❌ Пост `{key}` не найден.", parse_mode=ParseMode.MARKDOWN)

@dp.inline_query()
async def inline_query_handler(query: InlineQuery):
    """Обрабатывает inline-запросы @бот КЛЮЧ"""
    
    key = query.query.strip()
    
    if not key:
        # Пустой запрос — показываем последние посты
        templates = get_user_templates(query.from_user.id)
        results = []
        
        if templates:
            for t in templates[:5]:  # Показываем до 5 последних
                results.append(
                    InlineQueryResultArticle(
                        id=t['id'],
                        title=f'📄 {t["title"]}',
                        description=f'Ключ: {t["id"]}',
                        input_message_content=InputTextMessageContent(
                            message_text=f'Пост с ключом {t["id"]} (выбери этот вариант)',
                            parse_mode=ParseMode.MARKDOWN
                        )
                    )
                )
        else:
            results.append(
                InlineQueryResultArticle(
                    id='help',
                    title='📝 Как использовать',
                    description='Введи ключ поста после @бота',
                    input_message_content=InputTextMessageContent(
                        message_text='Введи ключ поста, например: `@твой_бот ABC123`',
                        parse_mode=ParseMode.MARKDOWN
                    )
                )
            )
        
        await query.answer(results, cache_time=1)
        return
    
    # Ищем шаблон по ключу
    template = get_template(key)
    
    if not template:
        results = [
            InlineQueryResultArticle(
                id='not_found',
                title='❌ Пост не найден',
                description=f'Пост с ключом "{key}" не существует',
                input_message_content=InputTextMessageContent(
                    message_text=f'❌ Пост с ключом "{key}" не найден.'
                )
            )
        ]
        await query.answer(results, cache_time=1)
        return
    
    # Создаем клавиатуру, если есть кнопки
    reply_markup = None
    if template['buttons']:
        builder = InlineKeyboardBuilder()
        for row in template['buttons']:
            for btn in row:
                builder.button(text=btn['text'], url=btn['url'])
        builder.adjust(1)
        reply_markup = builder.as_markup()
    
    # Создаем контент сообщения
    if template['media_type'] == 'photo' and template['media_id']:
        input_content = InputTextMessageContent(
            message_text=template['content'],
            parse_mode=ParseMode.MARKDOWN
        )
        # В реальном проекте здесь нужно использовать InputMediaPhoto
        # Но для простоты пока оставляем текст
    elif template['media_type'] == 'video' and template['media_id']:
        input_content = InputTextMessageContent(
            message_text=template['content'],
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        input_content = InputTextMessageContent(
            message_text=template['content'],
            parse_mode=ParseMode.MARKDOWN
        )
    
    results = [
        InlineQueryResultArticle(
            id=key,
            title=f'📄 {template["title"]}',
            description='Нажми, чтобы отправить',
            input_message_content=input_content,
            reply_markup=reply_markup
        )
    ]
    
    await query.answer(results, cache_time=1)

async def main():
    logger.info("🚀 Бот-генератор запускается...")
    await bot.delete_webhook()
    await dp.start_polling(bot)

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
