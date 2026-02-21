import os
import logging
import json
import sqlite3
import random
import string
import re
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Токен бота из переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

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
                  created_at TIMESTAMP)''')
    conn.commit()
    conn.close()

init_db()

def generate_key() -> str:
    """Генерирует короткий ключ для шаблона"""
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=8))

def save_template(user_id: int, title: str, content: str, buttons: list) -> str:
    """Сохраняет шаблон в базу"""
    key = generate_key()
    conn = sqlite3.connect('templates.db')
    c = conn.cursor()
    c.execute('''INSERT INTO templates (id, user_id, title, content, buttons, created_at)
                 VALUES (?, ?, ?, ?, ?, ?)''',
              (key, user_id, title, content, json.dumps(buttons), datetime.now()))
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
            'buttons': json.loads(row[4]) if row[4] else []
        }
    return None

def get_user_templates(user_id: int) -> list:
    """Возвращает список шаблонов пользователя"""
    conn = sqlite3.connect('templates.db')
    c = conn.cursor()
    c.execute('''SELECT id, title, created_at FROM templates 
                 WHERE user_id = ? ORDER BY created_at DESC''', (user_id,))
    rows = c.fetchall()
    conn.close()
    return [{'id': r[0], 'title': r[1]} for r in rows]

@dp.message(Command('start'))
async def cmd_start(message: types.Message):
    """Приветствие"""
    await message.answer(
        "🤖 **Генератор постов**\n\n"
        "Я помогаю создавать посты с кнопками!\n\n"
        "**Команды:**\n"
        "/new — создать новый пост\n"
        "/list — мои посты\n"
        "/help — справка\n\n"
        "**Как использовать:**\n"
        "1. Создай пост через /new\n"
        "2. Получи ключ\n"
        "3. В любом чате введи `@твой_бот КЛЮЧ`",
        parse_mode='Markdown'
    )

@dp.message(Command('help'))
async def cmd_help(message: types.Message):
    await message.answer(
        "**📖 Подробная справка**\n\n"
        "**/new** — создать новый пост\n"
        "   После команды просто отправь текст поста\n"
        "   Можно добавить кнопки в формате:\n"
        "   `[Кнопка 1 | https://ссылка1.ru]`\n"
        "   `[Кнопка 2 | https://ссылка2.ru]`\n\n"
        "**/list** — список всех твоих постов\n\n"
        "**/delete КЛЮЧ** — удалить пост\n\n"
        "**Inline-режим:**\n"
        "Введи `@твой_бот КЛЮЧ` в любом чате\n"
        "и выбери появившийся вариант",
        parse_mode='Markdown'
    )

@dp.message(Command('new'))
async def cmd_new(message: types.Message):
    """Создание нового поста"""
    await message.answer(
        "📝 **Создание нового поста**\n\n"
        "Отправь мне текст поста.\n"
        "Если хочешь добавить кнопки-ссылки, добавь их в формате:\n"
        "`[Текст кнопки | https://ссылка.ru]`\n\n"
        "Пример:\n"
        "`Привет! Вот наши туры:\n"
        "[На Байкал | https://baikal.ru]\n"
        "[На Алтай | https://altai.ru]`",
        parse_mode='Markdown'
    )

@dp.message()
async def handle_post_creation(message: types.Message):
    """Обрабатывает создание поста"""
    # Проверяем, что это не команда
    if message.text and not message.text.startswith('/'):
        text = message.text
        
        # Парсим кнопки из текста
        button_pattern = r'\[(.*?)\s*\|\s*(https?://[^\]]+)\]'
        buttons = []
        
        # Ищем все кнопки в тексте
        for match in re.finditer(button_pattern, text):
            button_text = match.group(1).strip()
            button_url = match.group(2).strip()
            buttons.append([{
                'text': button_text,
                'url': button_url
            }])
        
        # Удаляем разметку кнопок из текста для сохранения
        clean_text = re.sub(button_pattern, '', text).strip()
        
        # Сохраняем шаблон
        title = clean_text[:30] + '...' if len(clean_text) > 30 else clean_text
        key = save_template(
            user_id=message.from_user.id,
            title=title,
            content=clean_text,
            buttons=buttons
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
        
        preview_text = f"**Предпросмотр поста:**\n\n{clean_text}"
        await message.answer(preview_text, reply_markup=kb, parse_mode='Markdown')
        
        # Отправляем ключ
        await message.answer(
            f"✅ **Пост сохранен!**\n\n"
            f"**Ключ:** `{key}`\n\n"
            f"Чтобы опубликовать, введи в группе:\n"
            f"`@{message.bot.username} {key}`",
            parse_mode='Markdown'
        )

@dp.message(Command('list'))
async def cmd_list(message: types.Message):
    """Показывает список сохраненных постов"""
    templates = get_user_templates(message.from_user.id)
    
    if not templates:
        await message.answer("📭 У тебя пока нет сохраненных постов.")
        return
    
    text = "**📋 Твои посты:**\n\n"
    for t in templates:
        text += f"🔹 `{t['id']}` — {t['title']}\n"
    
    await message.answer(text, parse_mode='Markdown')

@dp.message(Command('delete'))
async def cmd_delete(message: types.Message):
    """Удаляет пост по ключу"""
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("❌ Укажи ключ: `/delete ABC123`", parse_mode='Markdown')
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
        await message.answer(f"✅ Пост `{key}` удален.", parse_mode='Markdown')
    else:
        await message.answer(f"❌ Пост `{key}` не найден.", parse_mode='Markdown')

@dp.inline_query()
async def inline_query_handler(query: InlineQuery):
    """Обрабатывает inline-запросы @бот КЛЮЧ"""
    logger.info(f"Inline query: {query.query}")
    
    key = query.query.strip()
    
    if not key:
        # Пустой запрос — показываем помощь
        results = [
            InlineQueryResultArticle(
                id='help',
                title='📝 Как использовать',
                description='Введи ключ поста после @бота',
                input_message_content=InputTextMessageContent(
                    message_text='Введи ключ поста, например: `@твой_бот ABC123`',
                    parse_mode='Markdown'
                )
            )
        ]
        await query.answer(results, cache_time=1)
        return
    
    # Ищем шаблон
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
    
    # Создаем результат для inline
    results = [
        InlineQueryResultArticle(
            id=key,
            title=f'📄 {template["title"]}',
            description='Нажми, чтобы отправить',
            input_message_content=InputTextMessageContent(
                message_text=template['content'],
                parse_mode='Markdown'
            ),
            reply_markup=reply_markup
        )
    ]
    
    await query.answer(results, cache_time=1)

async def main():
    logger.info("🚀 Бот-генератор запускается...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
