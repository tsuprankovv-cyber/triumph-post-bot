import os
import logging
import json
import sqlite3
import re
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
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
    c.execute('''CREATE TABLE IF NOT EXISTS saved_buttons
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  button_text TEXT,
                  button_url TEXT,
                  created_at TIMESTAMP)''')
    conn.commit()
    conn.close()

init_db()

# ==================== ФУНКЦИИ ДЛЯ РАБОТЫ С БАЗОЙ ====================

def button_exists(user_id: int, text: str, url: str) -> bool:
    """Проверяет, существует ли уже такая кнопка (по тексту И ссылке)"""
    conn = sqlite3.connect('templates.db')
    c = conn.cursor()
    c.execute('''SELECT id FROM saved_buttons 
                 WHERE user_id = ? AND button_text = ? AND button_url = ?''', 
              (user_id, text, url))
    exists = c.fetchone() is not None
    conn.close()
    return exists

def save_button(user_id: int, text: str, url: str):
    """Сохраняет кнопку в базу часто используемых (только если нет такой же)"""
    if button_exists(user_id, text, url):
        logger.info(f"⏭️ Кнопка уже существует: {text} - {url}")
        return False
    
    conn = sqlite3.connect('templates.db')
    c = conn.cursor()
    c.execute('''INSERT INTO saved_buttons (user_id, button_text, button_url, created_at)
                 VALUES (?, ?, ?, ?)''', (user_id, text, url, datetime.now()))
    conn.commit()
    conn.close()
    logger.info(f"✅ Новая кнопка сохранена: {text}")
    return True

def get_saved_buttons(user_id: int) -> list:
    """Возвращает все сохраненные кнопки пользователя"""
    conn = sqlite3.connect('templates.db')
    c = conn.cursor()
    c.execute('''SELECT id, button_text, button_url FROM saved_buttons 
                 WHERE user_id = ? ORDER BY created_at DESC''', (user_id,))
    rows = c.fetchall()
    conn.close()
    return [{'id': r[0], 'text': r[1], 'url': r[2]} for r in rows]

def delete_button(button_id: int, user_id: int) -> bool:
    """Удаляет кнопку по ID"""
    conn = sqlite3.connect('templates.db')
    c = conn.cursor()
    c.execute('DELETE FROM saved_buttons WHERE id = ? AND user_id = ?', (button_id, user_id))
    deleted = c.rowcount > 0
    conn.commit()
    conn.close()
    return deleted

def update_button(button_id: int, user_id: int, new_text: str, new_url: str) -> bool:
    """Обновляет текст и URL кнопки"""
    conn = sqlite3.connect('templates.db')
    c = conn.cursor()
    c.execute('''UPDATE saved_buttons 
                 SET button_text = ?, button_url = ?, created_at = ? 
                 WHERE id = ? AND user_id = ?''', 
              (new_text, new_url, datetime.now(), button_id, user_id))
    updated = c.rowcount > 0
    conn.commit()
    conn.close()
    return updated

# ==================== FSM СОСТОЯНИЯ ====================

class PostForm(StatesGroup):
    waiting_for_content = State()
    waiting_for_buttons = State()

class EditButtonForm(StatesGroup):
    waiting_for_new_text = State()
    waiting_for_new_url = State()

class AddButtonForm(StatesGroup):
    waiting_for_button_text = State()
    waiting_for_button_url = State()

# ==================== КЛАВИАТУРЫ ====================

def main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="➕ Новый пост")
    builder.button(text="📚 Мои кнопки")
    builder.button(text="❓ Помощь")
    builder.adjust(2, 1)
    return builder.as_markup(resize_keyboard=True, input_field_placeholder="Выбери действие...")

def cancel_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="❌ Отмена")
    return builder.as_markup(resize_keyboard=True)

def post_creation_keyboard():
    """Клавиатура для режима создания поста"""
    builder = ReplyKeyboardBuilder()
    builder.button(text="➕ Добавить кнопки")
    builder.button(text="📚 Мои кнопки")
    builder.button(text="✅ Готово")
    builder.button(text="❌ Отмена")
    builder.adjust(2, 2)
    return builder.as_markup(resize_keyboard=True)

# ==================== ОБРАБОТЧИКИ КОМАНД ====================

@dp.message(Command('start'))
async def cmd_start(message: types.Message):
    await message.answer(
        "🤖 **Генератор постов**\n\n"
        "🔹 **➕ Новый пост** — создать пост с кнопками\n"
        "🔹 **📚 Мои кнопки** — управление сохраненными кнопками\n"
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

@dp.message(F.text == "📚 Мои кнопки")
async def cmd_my_buttons(message: types.Message):
    """Показывает все сохраненные кнопки отдельными сообщениями"""
    buttons = get_saved_buttons(message.from_user.id)
    
    if not buttons:
        await message.answer(
            "📚 У тебя пока нет сохраненных кнопок.\n"
            "Нажми **➕ Новая кнопка** чтобы создать первую!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_keyboard()
        )
        return
    
    await message.answer(
        "**📚 Твои сохраненные кнопки:**\n\n"
        "Каждая кнопка показана отдельно. Используй кнопки под сообщением:",
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Показываем каждую кнопку отдельным сообщением
    for btn in buttons:
        # Клавиатура для действий с кнопкой
        builder = InlineKeyboardBuilder()
        builder.row(
            types.InlineKeyboardButton(
                text="📋 Скопировать", 
                callback_data=f"copy_btn:{btn['id']}"
            ),
            types.InlineKeyboardButton(
                text="✏️ Редактировать", 
                callback_data=f"edit_btn:{btn['id']}"
            ),
            types.InlineKeyboardButton(
                text="🗑️ Удалить", 
                callback_data=f"delete_btn:{btn['id']}"
            )
        )
        
        # Текст сообщения
        button_text = (
            f"**📌 Текст:** `{btn['text']}`\n"
            f"**🔗 Ссылка:** `{btn['url']}`"
        )
        
        await message.answer(
            button_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=builder.as_markup()
        )
    
    # Кнопки навигации
    nav_builder = ReplyKeyboardBuilder()
    nav_builder.button(text="➕ Новая кнопка")
    nav_builder.button(text="◀️ Назад")
    nav_builder.adjust(2)
    
    await message.answer(
        "Выбери действие:",
        reply_markup=nav_builder.as_markup(resize_keyboard=True)
    )

@dp.message(F.text == "➕ Новая кнопка")
async def cmd_add_button(message: types.Message, state: FSMContext):
    """Начинает процесс добавления новой кнопки в память"""
    await state.set_state(AddButtonForm.waiting_for_button_text)
    await message.answer(
        "➕ **Добавление новой кнопки**\n\n"
        "Введи **текст** для новой кнопки:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=cancel_keyboard()
    )

@dp.message(AddButtonForm.waiting_for_button_text)
async def process_add_button_text(message: types.Message, state: FSMContext):
    """Получает текст новой кнопки"""
    await state.update_data(new_button_text=message.text)
    await state.set_state(AddButtonForm.waiting_for_button_url)
    
    await message.answer(
        "➕ **Добавление новой кнопки**\n\n"
        "Теперь введи **ссылку** для кнопки:",
        parse_mode=ParseMode.MARKDOWN
    )

@dp.message(AddButtonForm.waiting_for_button_url)
async def process_add_button_url(message: types.Message, state: FSMContext):
    """Получает ссылку и сохраняет новую кнопку"""
    data = await state.get_data()
    button_text = data.get('new_button_text')
    button_url = message.text.strip()
    
    # Проверяем ссылку
    if not (button_url.startswith(('http://', 'https://', 'tg://', 't.me/'))):
        await message.answer(
            "❌ Неверный формат ссылки. Ссылка должна начинаться с http://, https://, tg:// или t.me/",
            reply_markup=main_keyboard()
        )
        await state.clear()
        return
    
    if button_url.startswith('t.me/'):
        button_url = 'https://' + button_url
    
    # Сохраняем кнопку в базу (только если новая)
    if save_button(message.from_user.id, button_text, button_url):
        await message.answer(
            f"✅ **Кнопка сохранена!**\n\n"
            f"**Текст:** `{button_text}`\n"
            f"**Ссылка:** `{button_url}`",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await message.answer(
            f"⚠️ **Кнопка не добавлена**\n\n"
            f"Такая кнопка (с таким же текстом и ссылкой) уже существует.",
            parse_mode=ParseMode.MARKDOWN
        )
    
    # Показываем обновленный список кнопок
    await cmd_my_buttons(message)
    await state.clear()

@dp.message(F.text == "◀️ Назад")
async def cmd_back(message: types.Message, state: FSMContext):
    """Возврат в главное меню"""
    await state.clear()
    await cmd_start(message)

@dp.message(F.text == "❓ Помощь")
async def cmd_help(message: types.Message):
    await message.answer(
        "**📖 Помощь**\n\n"
        "**Как создать пост:**\n"
        "1. Нажми **➕ Новый пост**\n"
        "2. Отправь текст/фото/видео\n"
        "3. Нажми **➕ Добавить кнопки** или **📚 Мои кнопки**\n"
        "4. Введи кнопки в формате:\n"
        "   `Текст - ссылка`\n"
        "   или `Кнопка1 - url1 | Кнопка2 - url2`\n"
        "5. Нажми **✅ Готово** — пост готов к пересылке\n\n"
        "**Управление кнопками:**\n"
        "• В разделе **📚 Мои кнопки** можно:\n"
        "  - Копировать кнопку (📋)\n"
        "  - Редактировать (✏️)\n"
        "  - Удалять (🗑️)\n"
        "  - Добавить новую (➕ Новая кнопка)\n"
        "  - При создании поста можно выбрать несколько кнопок сразу",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_keyboard()
    )

@dp.message(F.text == "❌ Отмена")
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Действие отменено", reply_markup=main_keyboard())

# ==================== ОБРАБОТЧИКИ ДЛЯ INLINE-КНОПОК (МОИ КНОПКИ) ====================

@dp.callback_query(lambda c: c.data.startswith('copy_btn:'))
async def copy_button_callback(callback: types.CallbackQuery):
    """Отправляет кнопку в формате для копирования"""
    button_id = int(callback.data.split(':')[1])
    buttons = get_saved_buttons(callback.from_user.id)
    
    btn = next((b for b in buttons if b['id'] == button_id), None)
    if not btn:
        await callback.answer("❌ Кнопка не найдена")
        return
    
    # Отправляем отдельным сообщением для копирования
    await callback.message.answer(
        f"`{btn['text']} - {btn['url']}`\n\n"
        f"✅ Скопируй эту строку и вставь при добавлении кнопок",
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer("✅ Строка для копирования отправлена выше")

@dp.callback_query(lambda c: c.data.startswith('edit_btn:'))
async def edit_button_callback(callback: types.CallbackQuery, state: FSMContext):
    """Начинает процесс редактирования кнопки"""
    button_id = int(callback.data.split(':')[1])
    buttons = get_saved_buttons(callback.from_user.id)
    
    btn = next((b for b in buttons if b['id'] == button_id), None)
    if not btn:
        await callback.answer("❌ Кнопка не найдена")
        return
    
    # Сохраняем ID редактируемой кнопки
    await state.update_data(editing_button_id=button_id)
    await state.set_state(EditButtonForm.waiting_for_new_text)
    
    # Показываем текущие значения для редактирования
    await callback.message.answer(
        f"✏️ **Редактирование кнопки**\n\n"
        f"**Текущий текст:** `{btn['text']}`\n"
        f"**Текущая ссылка:** `{btn['url']}`\n\n"
        f"Введи **новый текст** для кнопки:",
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()

@dp.message(EditButtonForm.waiting_for_new_text)
async def process_edit_text(message: types.Message, state: FSMContext):
    """Получает новый текст кнопки"""
    await state.update_data(new_text=message.text)
    await state.set_state(EditButtonForm.waiting_for_new_url)
    
    await message.answer(
        "✏️ **Редактирование кнопки**\n\n"
        "Теперь введи **новую ссылку**:",
        parse_mode=ParseMode.MARKDOWN
    )

@dp.message(EditButtonForm.waiting_for_new_url)
async def process_edit_url(message: types.Message, state: FSMContext):
    """Получает новую ссылку и сохраняет изменения"""
    data = await state.get_data()
    button_id = data.get('editing_button_id')
    new_text = data.get('new_text')
    new_url = message.text.strip()
    
    # Проверяем ссылку
    if not (new_url.startswith(('http://', 'https://', 'tg://', 't.me/'))):
        await message.answer(
            "❌ Неверный формат ссылки. Ссылка должна начинаться с http://, https://, tg:// или t.me/",
            reply_markup=main_keyboard()
        )
        await state.clear()
        return
    
    if new_url.startswith('t.me/'):
        new_url = 'https://' + new_url
    
    # Обновляем в базе
    if update_button(button_id, message.from_user.id, new_text, new_url):
        await message.answer(
            f"✅ **Кнопка обновлена!**\n\n"
            f"**Новый текст:** `{new_text}`\n"
            f"**Новая ссылка:** `{new_url}`",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Показываем обновленный список кнопок
        await cmd_my_buttons(message)
    else:
        await message.answer(
            "❌ Ошибка при обновлении кнопки",
            reply_markup=main_keyboard()
        )
    
    await state.clear()

@dp.callback_query(lambda c: c.data.startswith('delete_btn:'))
async def delete_button_callback(callback: types.CallbackQuery):
    """Удаляет кнопку"""
    button_id = int(callback.data.split(':')[1])
    
    if delete_button(button_id, callback.from_user.id):
        await callback.answer("✅ Кнопка удалена")
        # Удаляем сообщение с этой кнопкой
        await callback.message.delete()
    else:
        await callback.answer("❌ Не удалось удалить кнопку")

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
        await message.answer("📸 **Фото получено!**\n\nТеперь добавь кнопки", 
                           parse_mode=ParseMode.MARKDOWN, reply_markup=post_creation_keyboard())
    elif message.video:
        content_data['media_type'] = 'video'
        content_data['media_id'] = message.video.file_id
        await message.answer("🎬 **Видео получено!**\n\nТеперь добавь кнопки", 
                           parse_mode=ParseMode.MARKDOWN, reply_markup=post_creation_keyboard())
    elif message.text:
        await message.answer("✍️ **Текст получен!**\n\nТеперь добавь кнопки", 
                           parse_mode=ParseMode.MARKDOWN, reply_markup=post_creation_keyboard())
    else:
        await message.answer("❌ Неподдерживаемый формат. Отправь текст, фото или видео.")
        return
    
    await state.update_data(content_data)
    await state.set_state(PostForm.waiting_for_buttons)

# ==================== ШАГ 2: ДОБАВЛЕНИЕ КНОПОК (С МНОЖЕСТВЕННЫМ ВЫБОРОМ) ====================

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
        reply_markup=post_creation_keyboard()
    )

@dp.message(PostForm.waiting_for_buttons, F.text == "📚 Мои кнопки")
async def use_saved_buttons(message: types.Message, state: FSMContext):
    """Показывает сохраненные кнопки для множественного выбора и добавления в пост"""
    buttons = get_saved_buttons(message.from_user.id)
    
    if not buttons:
        await message.answer(
            "📚 У тебя пока нет сохраненных кнопок.",
            reply_markup=post_creation_keyboard()
        )
        return
    
    # Получаем текущее состояние, чтобы отметить уже выбранные кнопки
    data = await state.get_data()
    existing_buttons = data.get('buttons', [])
    selected_buttons = data.get('selected_buttons', [])
    
    # Создаем множество уже выбранных текстов (для отметки)
    selected_texts = set()
    
    # Добавляем уже примененные кнопки
    for row in existing_buttons:
        for btn in row:
            selected_texts.add(btn['text'])
    
    # Добавляем временно выбранные
    for btn in selected_buttons:
        selected_texts.add(btn['text'])
    
    # Создаем клавиатуру с кнопками для выбора
    builder = InlineKeyboardBuilder()
    
    for btn in buttons:
        # Проверяем, выбрана ли уже эта кнопка
        is_selected = btn['text'] in selected_texts
        prefix = "✅ " if is_selected else "🔘 "
        
        builder.button(
            text=f"{prefix}{btn['text'][:30]}", 
            callback_data=f"select_btn:{btn['id']}"
        )
    
    # Кнопки управления
    builder.row(
        types.InlineKeyboardButton(
            text="✅ Применить выбранные", 
            callback_data="apply_selected_buttons"
        ),
        types.InlineKeyboardButton(
            text="🔄 Сбросить все", 
            callback_data="clear_selected_buttons"
        )
    )
    builder.row(
        types.InlineKeyboardButton(
            text="◀️ Назад", 
            callback_data="back_to_post_creation"
        )
    )
    
    builder.adjust(2)
    
    await message.answer(
        "**📚 Выбери кнопки для добавления в пост:**\n\n"
        "🔘 — не выбрана\n"
        "✅ — выбрана\n"
        "Можно выбрать несколько. После выбора нажми **✅ Применить**",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=builder.as_markup()
    )

@dp.callback_query(lambda c: c.data.startswith('select_btn:'))
async def select_button_callback(callback: types.CallbackQuery, state: FSMContext):
    """Выбирает или отменяет выбор кнопки для добавления в пост"""
    button_id = int(callback.data.split(':')[1])
    buttons = get_saved_buttons(callback.from_user.id)
    
    btn = next((b for b in buttons if b['id'] == button_id), None)
    if not btn:
        await callback.answer("❌ Кнопка не найдена")
        return
    
    # Получаем текущие выбранные кнопки из состояния
    data = await state.get_data()
    existing_buttons = data.get('buttons', [])
    selected_buttons = data.get('selected_buttons', [])
    
    # Проверяем, выбрана ли уже эта кнопка
    is_selected = False
    
    # Проверяем в уже примененных
    for row in existing_buttons:
        for b in row:
            if b['text'] == btn['text'] and b['url'] == btn['url']:
                is_selected = True
                break
    
    # Проверяем во временном хранилище
    if not is_selected:
        for b in selected_buttons:
            if b['text'] == btn['text'] and b['url'] == btn['url']:
                is_selected = True
                break
    
    if is_selected:
        # Убираем из временного хранилища
        selected_buttons = [b for b in selected_buttons 
                           if not (b['text'] == btn['text'] and b['url'] == btn['url'])]
        await callback.answer("❌ Кнопка убрана из выбранных")
    else:
        # Добавляем во временное хранилище
        selected_buttons.append({'text': btn['text'], 'url': btn['url']})
        await callback.answer("✅ Кнопка добавлена в выбранные")
    
    await state.update_data(selected_buttons=selected_buttons)
    
    # Обновляем сообщение со списком кнопок
    await update_buttons_list(callback.message, state, callback.from_user.id)

async def update_buttons_list(message: types.Message, state: FSMContext, user_id: int):
    """Обновляет сообщение со списком кнопок, показывая выбранные"""
    buttons = get_saved_buttons(user_id)
    data = await state.get_data()
    existing_buttons = data.get('buttons', [])
    selected_buttons = data.get('selected_buttons', [])
    
    # Создаем множество выбранных текстов
    selected_texts = set()
    
    # Добавляем уже примененные кнопки
    for row in existing_buttons:
        for btn in row:
            selected_texts.add(btn['text'])
    
    # Добавляем временно выбранные
    for btn in selected_buttons:
        selected_texts.add(btn['text'])
    
    # Создаем клавиатуру
    builder = InlineKeyboardBuilder()
    
    for btn in buttons:
        is_selected = btn['text'] in selected_texts
        prefix = "✅ " if is_selected else "🔘 "
        
        builder.button(
            text=f"{prefix}{btn['text'][:30]}", 
            callback_data=f"select_btn:{btn['id']}"
        )
    
    builder.row(
        types.InlineKeyboardButton(
            text="✅ Применить выбранные", 
            callback_data="apply_selected_buttons"
        ),
        types.InlineKeyboardButton(
            text="🔄 Сбросить все", 
            callback_data="clear_selected_buttons"
        )
    )
    builder.row(
        types.InlineKeyboardButton(
            text="◀️ Назад", 
            callback_data="back_to_post_creation"
        )
    )
    
    builder.adjust(2)
    
    await message.edit_text(
        "**📚 Выбери кнопки для добавления в пост:**\n\n"
        "🔘 — не выбрана\n"
        "✅ — выбрана\n"
        "Можно выбрать несколько. После выбора нажми **✅ Применить**",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=builder.as_markup()
    )

@dp.callback_query(lambda c: c.data == "apply_selected_buttons")
async def apply_selected_buttons_callback(callback: types.CallbackQuery, state: FSMContext):
    """Применяет все выбранные кнопки к посту"""
    data = await state.get_data()
    selected_buttons = data.get('selected_buttons', [])
    existing_buttons = data.get('buttons', [])
    
    if not selected_buttons:
        await callback.answer("❌ Нет выбранных кнопок")
        return
    
    # Добавляем все выбранные кнопки к существующим
    for btn in selected_buttons:
        existing_buttons.append([btn])
    
    await state.update_data(buttons=existing_buttons, selected_buttons=[])
    
    # Удаляем сообщение со списком
    await callback.message.delete()
    
    # Показываем обновленный предпросмотр
    await show_preview(callback.message, state)
    
    # Возвращаемся в режим добавления кнопок
    await callback.message.answer(
        f"✅ Добавлено {len(selected_buttons)} кнопок!\n"
        f"Можешь добавить еще или нажать **✅ Готово**",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=post_creation_keyboard()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "clear_selected_buttons")
async def clear_selected_buttons_callback(callback: types.CallbackQuery, state: FSMContext):
    """Сбрасывает все выбранные кнопки"""
    await state.update_data(selected_buttons=[])
    await update_buttons_list(callback.message, state, callback.from_user.id)
    await callback.answer("🔄 Выбор сброшен")

@dp.callback_query(lambda c: c.data == 'back_to_post_creation')
async def back_to_post_creation(callback: types.CallbackQuery, state: FSMContext):
    """Возврат к созданию поста"""
    await callback.message.delete()
    await callback.message.answer(
        "Продолжай добавление кнопок или нажми **✅ Готово**",
        reply_markup=post_creation_keyboard()
    )
    await callback.answer()

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
                        # Сохраняем в базу (только если новая)
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
                    # Сохраняем в базу (только если новая)
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
            reply_markup=post_creation_keyboard()
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
    
    # Отправляем предпросмотр
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
    
    # Очищаем состояние
    await state.clear()
    
    # Показываем финальный пост
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
    
    # Возвращаем главное меню
    await message.answer(
        "✅ **Пост готов!**\n\n"
        "Теперь ты можешь переслать его в группу "
        "с опцией **«Скрыть отправителя»**",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_keyboard()
    )

# ==================== ЗАПУСК ====================

async def main():
    logger.info("🚀 Бот-генератор с множественным выбором запускается...")
    await bot.delete_webhook()
    await dp.start_polling(bot)

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
