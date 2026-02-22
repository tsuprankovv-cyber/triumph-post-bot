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
    conn = sqlite3.connect('templates.db')
    c = conn.cursor()
    c.execute('''SELECT id FROM saved_buttons 
                 WHERE user_id = ? AND button_text = ? AND button_url = ?''', 
              (user_id, text, url))
    exists = c.fetchone() is not None
    conn.close()
    return exists

def save_button(user_id: int, text: str, url: str):
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
    conn = sqlite3.connect('templates.db')
    c = conn.cursor()
    c.execute('''SELECT id, button_text, button_url FROM saved_buttons 
                 WHERE user_id = ? ORDER BY created_at DESC''', (user_id,))
    rows = c.fetchall()
    conn.close()
    return [{'id': r[0], 'text': r[1], 'url': r[2]} for r in rows]

def delete_button(button_id: int, user_id: int) -> bool:
    conn = sqlite3.connect('templates.db')
    c = conn.cursor()
    c.execute('DELETE FROM saved_buttons WHERE id = ? AND user_id = ?', (button_id, user_id))
    deleted = c.rowcount > 0
    conn.commit()
    conn.close()
    return deleted

def update_button(button_id: int, user_id: int, new_text: str, new_url: str) -> bool:
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
    
    for btn in buttons:
        builder = InlineKeyboardBuilder()
        builder.row(
            types.InlineKeyboardButton(text="📋 Скопировать", callback_data=f"copy_btn:{btn['id']}"),
            types.InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_btn:{btn['id']}"),
            types.InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"delete_btn:{btn['id']}")
        )
        
        button_text = f"**📌 Текст:** `{btn['text']}`\n**🔗 Ссылка:** `{btn['url']}`"
        await message.answer(button_text, parse_mode=ParseMode.MARKDOWN, reply_markup=builder.as_markup())
    
    nav_builder = ReplyKeyboardBuilder()
    nav_builder.button(text="➕ Новая кнопка")
    nav_builder.button(text="◀️ Назад")
    nav_builder.adjust(2)
    await message.answer("Выбери действие:", reply_markup=nav_builder.as_markup(resize_keyboard=True))

@dp.message(F.text == "➕ Новая кнопка")
async def cmd_add_button(message: types.Message, state: FSMContext):
    await state.set_state(AddButtonForm.waiting_for_button_text)
    await message.answer(
        "➕ **Добавление новой кнопки**\n\nВведи **текст** для новой кнопки:",
        parse_mode=ParseMode.MARKDOWN, reply_markup=cancel_keyboard()
    )

@dp.message(AddButtonForm.waiting_for_button_text)
async def process_add_button_text(message: types.Message, state: FSMContext):
    await state.update_data(new_button_text=message.text)
    await state.set_state(AddButtonForm.waiting_for_button_url)
    await message.answer("➕ **Добавление новой кнопки**\n\nТеперь введи **ссылку** для кнопки:", parse_mode=ParseMode.MARKDOWN)

@dp.message(AddButtonForm.waiting_for_button_url)
async def process_add_button_url(message: types.Message, state: FSMContext):
    data = await state.get_data()
    button_text = data.get('new_button_text')
    button_url = message.text.strip()
    
    if not (button_url.startswith(('http://', 'https://', 'tg://', 't.me/'))):
        await message.answer("❌ Неверный формат ссылки. Ссылка должна начинаться с http://, https://, tg:// или t.me/", reply_markup=main_keyboard())
        await state.clear()
        return
    
    if button_url.startswith('t.me/'):
        button_url = 'https://' + button_url
    
    if save_button(message.from_user.id, button_text, button_url):
        await message.answer(f"✅ **Кнопка сохранена!**\n\n**Текст:** `{button_text}`\n**Ссылка:** `{button_url}`", parse_mode=ParseMode.MARKDOWN)
    else:
        await message.answer(f"⚠️ **Кнопка не добавлена**\n\nТакая кнопка уже существует.", parse_mode=ParseMode.MARKDOWN)
    
    await cmd_my_buttons(message)
    await state.clear()

@dp.message(F.text == "◀️ Назад")
async def cmd_back(message: types.Message, state: FSMContext):
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
        "4. Выбери кнопки и нажми **✅ Применить**\n"
        "5. Нажми **✅ Готово** — пост готов к пересылке",
        parse_mode=ParseMode.MARKDOWN, reply_markup=main_keyboard()
    )
# ==================== ОБРАБОТЧИКИ ДЛЯ INLINE-КНОПОК ====================

@dp.callback_query(lambda c: c.data.startswith('copy_btn:'))
async def copy_button_callback(callback: types.CallbackQuery):
    button_id = int(callback.data.split(':')[1])
    buttons = get_saved_buttons(callback.from_user.id)
    btn = next((b for b in buttons if b['id'] == button_id), None)
    
    if not btn:
        await callback.answer("❌ Кнопка не найдена")
        return
    
    await callback.message.answer(
        f"`{btn['text']} - {btn['url']}`\n\n✅ Скопируй эту строку и вставь при добавлении кнопок",
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer("✅ Строка для копирования отправлена выше")

@dp.callback_query(lambda c: c.data.startswith('edit_btn:'))
async def edit_button_callback(callback: types.CallbackQuery, state: FSMContext):
    button_id = int(callback.data.split(':')[1])
    buttons = get_saved_buttons(callback.from_user.id)
    btn = next((b for b in buttons if b['id'] == button_id), None)
    
    if not btn:
        await callback.answer("❌ Кнопка не найдена")
        return
    
    await state.update_data(editing_button_id=button_id)
    await state.set_state(EditButtonForm.waiting_for_new_text)
    
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
    await state.update_data(new_text=message.text)
    await state.set_state(EditButtonForm.waiting_for_new_url)
    await message.answer("✏️ **Редактирование кнопки**\n\nТеперь введи **новую ссылку**:", parse_mode=ParseMode.MARKDOWN)

@dp.message(EditButtonForm.waiting_for_new_url)
async def process_edit_url(message: types.Message, state: FSMContext):
    data = await state.get_data()
    button_id = data.get('editing_button_id')
    new_text = data.get('new_text')
    new_url = message.text.strip()
    
    if not (new_url.startswith(('http://', 'https://', 'tg://', 't.me/'))):
        await message.answer("❌ Неверный формат ссылки", reply_markup=main_keyboard())
        await state.clear()
        return
    
    if new_url.startswith('t.me/'):
        new_url = 'https://' + new_url
    
    if update_button(button_id, message.from_user.id, new_text, new_url):
        await message.answer(f"✅ **Кнопка обновлена!**\n\n**Новый текст:** `{new_text}`\n**Новая ссылка:** `{new_url}`", parse_mode=ParseMode.MARKDOWN)
        await cmd_my_buttons(message)
    else:
        await message.answer("❌ Ошибка при обновлении кнопки", reply_markup=main_keyboard())
    
    await state.clear()

@dp.callback_query(lambda c: c.data.startswith('delete_btn:'))
async def delete_button_callback(callback: types.CallbackQuery):
    button_id = int(callback.data.split(':')[1])
    
    if delete_button(button_id, callback.from_user.id):
        await callback.answer("✅ Кнопка удалена")
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
    # ==================== МНОЖЕСТВЕННЫЙ ВЫБОР КНОПОК ====================

@dp.message(PostForm.waiting_for_buttons, F.text == "📚 Мои кнопки")
async def use_saved_buttons(message: types.Message, state: FSMContext):
    buttons = get_saved_buttons(message.from_user.id)
    
    if not buttons:
        await message.answer("📚 У тебя пока нет сохраненных кнопок.", reply_markup=post_creation_keyboard())
        return
    
    data = await state.get_data()
    existing_buttons = data.get('buttons', [])
    temp_selected = data.get('temp_selected', [])
    
    added_set = set()
    for row in existing_buttons:
        for btn in row:
            added_set.add(f"{btn['text']}|{btn['url']}")
    
    temp_set = {f"{btn['text']}|{btn['url']}" for btn in temp_selected}
    
    builder = InlineKeyboardBuilder()
    for btn in buttons:
        btn_key = f"{btn['text']}|{btn['url']}"
        is_selected = btn_key in added_set or btn_key in temp_set
        prefix = "✅ " if is_selected else "🔘 "
        builder.button(text=f"{prefix}{btn['text'][:30]}", callback_data=f"toggle_btn:{btn['id']}")
    
    builder.row(
        types.InlineKeyboardButton(text="✅ Применить выбранные", callback_data="apply_selected_buttons"),
        types.InlineKeyboardButton(text="🔄 Сбросить выбор", callback_data="clear_selected_buttons")
    )
    builder.row(
        types.InlineKeyboardButton(text="◀️ Назад к добавлению", callback_data="back_to_button_addition")
    )
    builder.adjust(2)
    
    await message.answer(
        "**📚 Выбери кнопки для добавления в пост:**\n\n"
        "🔘 — не выбрана\n✅ — выбрана\n"
        "Нажимай на кнопки, чтобы выбрать. После выбора нажми **✅ Применить**",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=builder.as_markup()
    )

@dp.callback_query(lambda c: c.data.startswith('toggle_btn:'))
async def toggle_button_callback(callback: types.CallbackQuery, state: FSMContext):
    button_id = int(callback.data.split(':')[1])
    buttons = get_saved_buttons(callback.from_user.id)
    btn = next((b for b in buttons if b['id'] == button_id), None)
    
    if not btn:
        await callback.answer("❌ Кнопка не найдена")
        return
    
    data = await state.get_data()
    temp_selected = data.get('temp_selected', [])
    existing_buttons = data.get('buttons', [])
    
    for row in existing_buttons:
        for b in row:
            if b['text'] == btn['text'] and b['url'] == btn['url']:
                await callback.answer("❌ Эта кнопка уже добавлена в пост")
                return
    
    found = None
    for i, b in enumerate(temp_selected):
        if b['text'] == btn['text'] and b['url'] == btn['url']:
            found = i
            break
    
    if found is not None:
        temp_selected.pop(found)
        await callback.answer("❌ Кнопка убрана из выбора")
    else:
        temp_selected.append({'text': btn['text'], 'url': btn['url']})
        await callback.answer("✅ Кнопка добавлена в выбор")
    
    await state.update_data(temp_selected=temp_selected)
    await update_buttons_display(callback.message, state, callback.from_user.id)

async def update_buttons_display(message: types.Message, state: FSMContext, user_id: int):
    buttons = get_saved_buttons(user_id)
    data = await state.get_data()
    existing_buttons = data.get('buttons', [])
    temp_selected = data.get('temp_selected', [])
    
    added_set = set()
    for row in existing_buttons:
        for btn in row:
            added_set.add(f"{btn['text']}|{btn['url']}")
    
    temp_set = {f"{btn['text']}|{btn['url']}" for btn in temp_selected}
    
    builder = InlineKeyboardBuilder()
    for btn in buttons:
        btn_key = f"{btn['text']}|{btn['url']}"
        is_selected = btn_key in added_set or btn_key in temp_set
        prefix = "✅ " if is_selected else "🔘 "
        builder.button(text=f"{prefix}{btn['text'][:30]}", callback_data=f"toggle_btn:{btn['id']}")
    
    builder.row(
        types.InlineKeyboardButton(text="✅ Применить выбранные", callback_data="apply_selected_buttons"),
        types.InlineKeyboardButton(text="🔄 Сбросить выбор", callback_data="clear_selected_buttons")
    )
    builder.row(
        types.InlineKeyboardButton(text="◀️ Назад к добавлению", callback_data="back_to_button_addition")
    )
    builder.adjust(2)
    
    await message.edit_text(
        "**📚 Выбери кнопки для добавления в пост:**\n\n"
        "🔘 — не выбрана\n✅ — выбрана\n"
        "Нажимай на кнопки, чтобы выбрать. После выбора нажми **✅ Применить**",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=builder.as_markup()
    )

@dp.callback_query(lambda c: c.data == "apply_selected_buttons")
async def apply_selected_buttons_callback(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    temp_selected = data.get('temp_selected', [])
    existing_buttons = data.get('buttons', [])
    
    if not temp_selected:
        await callback.answer("❌ Нет выбранных кнопок")
        return
    
    for btn in temp_selected:
        existing_buttons.append([btn])
    
    await state.update_data(buttons=existing_buttons, temp_selected=[])
    await callback.message.delete()
    await show_preview(callback.message, state)
    
    await callback.message.answer(
        f"✅ Добавлено {len(temp_selected)} кнопок!\nМожешь добавить еще или нажать **✅ Готово**",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=post_creation_keyboard()
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "clear_selected_buttons")
async def clear_selected_buttons_callback(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(temp_selected=[])
    await update_buttons_display(callback.message, state, callback.from_user.id)
    await callback.answer("🔄 Выбор сброшен")

@dp.callback_query(lambda c: c.data == 'back_to_button_addition')
async def back_to_button_addition(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(temp_selected=[])
    await callback.message.delete()
    await callback.message.answer(
        "Продолжай добавление кнопок или нажми **✅ Готово**",
        reply_markup=post_creation_keyboard()
    )
    await callback.answer()
    # ==================== ОБРАБОТКА РУЧНОГО ВВОДА КНОПОК ====================

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
    
    lines = text.strip().split('\n')
    all_buttons = []
    
    for line in lines:
        if '|' in line:
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
            parts = re.split(r'\s*[-|]\s*', line.strip(), maxsplit=1)
            if len(parts) == 2:
                btn_name, btn_url = parts
                if btn_url.startswith(('http://', 'https://', 'tg://', 't.me/')):
                    if btn_url.startswith('t.me/'):
                        btn_url = 'https://' + btn_url
                    all_buttons.append([{'text': btn_name.strip(), 'url': btn_url.strip()}])
                    save_button(message.from_user.id, btn_name.strip(), btn_url.strip())
    
    if all_buttons:
        data = await state.get_data()
        existing_buttons = data.get('buttons', [])
        existing_buttons.extend(all_buttons)
        await state.update_data(buttons=existing_buttons)
        await show_preview(message, state)
        await message.answer("✅ Кнопки добавлены!\nМожешь добавить еще или нажать **✅ Готово**",
                           reply_markup=post_creation_keyboard())
    else:
        await message.answer("❌ Не удалось распознать кнопки.\nИспользуй формат: `Текст - ссылка`",
                           parse_mode=ParseMode.MARKDOWN)

async def show_preview(message: types.Message, state: FSMContext):
    data = await state.get_data()
    content_text = data.get('text', '')
    media_type = data.get('media_type')
    media_id = data.get('media_id')
    buttons = data.get('buttons', [])
    
    kb = None
    if buttons:
        builder = InlineKeyboardBuilder()
        for row in buttons:
            for btn in row:
                builder.button(text=btn['text'], url=btn['url'])
        builder.adjust(1)
        kb = builder.as_markup()
    
    if media_type == 'photo' and media_id:
        await message.answer_photo(photo=media_id, caption=content_text or None, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
    elif media_type == 'video' and media_id:
        await message.answer_video(video=media_id, caption=content_text or None, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
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
    
    await state.clear()
    
    kb = None
    if buttons:
        builder = InlineKeyboardBuilder()
        for row in buttons:
            for btn in row:
                builder.button(text=btn['text'], url=btn['url'])
        builder.adjust(1)
        kb = builder.as_markup()
    
    if media_type == 'photo' and media_id:
        await message.answer_photo(photo=media_id, caption=content_text or None, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
    elif media_type == 'video' and media_id:
        await message.answer_video(video=media_id, caption=content_text or None, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
    else:
        if content_text:
            await message.answer(content_text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        elif buttons:
            await message.answer(" ", reply_markup=kb)
    
    await message.answer(
        "✅ **Пост готов!**\n\nТеперь ты можешь переслать его в группу с опцией **«Скрыть отправителя»**",
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
@dp.message(F.text == "❌ Отмена")
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Действие отменено", reply_markup=main_keyboard())
    
