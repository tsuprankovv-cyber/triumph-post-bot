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

def save_button(user_id: int, text: str, url: str):
    """Сохраняет кнопку в базу часто используемых"""
    conn = sqlite3.connect('templates.db')
    c = conn.cursor()
    c.execute('''INSERT INTO saved_buttons (user_id, button_text, button_url, created_at)
                 VALUES (?, ?, ?, ?)''', (user_id, text, url, datetime.now()))
    conn.commit()
    conn.close()

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

def buttons_action_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="➕ Добавить кнопки")
    builder.button(text="📚 Мои кнопки")
    builder.button(text="✅ Готово")
    builder.button(text="❌ Отмена")
    builder.adjust(2, 2)
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
async def cmd_my_buttons(message: types.Message, state: FSMContext):
    """Показывает список сохраненных кнопок с действиями"""
    buttons = get_saved_buttons(message.from_user.id)
    
    if not buttons:
        await message.answer(
            "📚 У тебя пока нет сохраненных кнопок.\n"
            "Они будут добавляться автоматически при создании постов.",
            reply_markup=main_keyboard()
        )
        return
    
    # Создаем клавиатуру со списком кнопок
    builder = InlineKeyboardBuilder()
    for btn in buttons:
        # Каждая кнопка: [Текст] [Копировать] [✏️] [🗑️]
        row = [
            types.InlineKeyboardButton(
                text=f"📌 {btn['text'][:20]}", 
                callback_data=f"view_btn:{btn['id']}"
            ),
            types.InlineKeyboardButton(
                text="📋", 
                callback_data=f"copy_btn:{btn['id']}"
            ),
            types.InlineKeyboardButton(
                text="✏️", 
                callback_data=f"edit_btn:{btn['id']}"
            ),
            types.InlineKeyboardButton(
                text="🗑️", 
                callback_data=f"delete_btn:{btn['id']}"
            )
        ]
        builder.row(*row)
    
    # Кнопка возврата в главное меню
    builder.row(types.InlineKeyboardButton(
        text="◀️ Назад", 
        callback_data="back_to_main"
    ))
    
    await message.answer(
        "**📚 Твои сохраненные кнопки:**\n\n"
        "Нажми на кнопку для просмотра или используй иконки:\n"
        "📋 — скопировать\n"
        "✏️ — редактировать\n"
        "🗑️ — удалить",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=builder.as_markup()
    )

@dp.callback_query(lambda c: c.data.startswith('view_btn:'))
async def view_button_callback(callback: types.CallbackQuery):
    """Показывает содержимое кнопки"""
    button_id = int(callback.data.split(':')[1])
    buttons = get_saved_buttons(callback.from_user.id)
    
    btn = next((b for b in buttons if b['id'] == button_id), None)
    if not btn:
        await callback.answer("❌ Кнопка не найдена")
        return
    
    # Создаем клавиатуру для просмотра
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text="📋 Скопировать", 
            callback_data=f"copy_btn:{button_id}"
        ),
        types.InlineKeyboardButton(
            text="✏️ Редактировать", 
            callback_data=f"edit_btn:{button_id}"
        )
    )
    builder.row(
        types.InlineKeyboardButton(
            text="🗑️ Удалить", 
            callback_data=f"delete_btn:{button_id}"
        ),
        types.InlineKeyboardButton(
            text="◀️ Назад", 
            callback_data="back_to_buttons"
        )
    )
    
    await callback.message.edit_text(
        f"**📌 Кнопка:**\n"
        f"**Текст:** {btn['text']}\n"
        f"**Ссылка:** {btn['url']}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=builder.as_markup()
    )
    await callback.answer()

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
    await callback.answer("✅ Скопировано в сообщение выше")

@dp.callback_query(lambda c: c.data.startswith('edit_btn:'))
async def edit_button_callback(callback: types.CallbackQuery, state: FSMContext):
    """Начинает процесс редактирования кнопки"""
    button_id = int(callback.data.split(':')[1])
    
    await state.update_data(editing_button_id=button_id)
    await state.set_state(EditButtonForm.waiting_for_new_text)
    
    await callback.message.edit_text(
        "✏️ **Редактирование кнопки**\n\n"
        "Введи **новый текст** для кнопки:",
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
            "✅ **Кнопка обновлена!**",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_keyboard()
        )
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
        # Возвращаемся к списку кнопок
        await cmd_my_buttons(callback.message, None)
    else:
        await callback.answer("❌ Не удалось удалить кнопку")

@dp.callback_query(lambda c: c.data == 'back_to_buttons')
async def back_to_buttons_callback(callback: types.CallbackQuery):
    """Возврат к списку кнопок"""
    await cmd_my_buttons(callback.message, None)
    await callback.answer()

@dp.callback_query(lambda c: c.data == 'back_to_main')
async def back_to_main_callback(callback: types.CallbackQuery, state: FSMContext):
    """Возврат в главное меню"""
    await state.clear()
    await callback.message.delete()
    await cmd_start(callback.message)
    await callback.answer()

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
        "  - Удалять (🗑️)",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_keyboard()
    )

@dp.message(F.text == "❌ Отмена")
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
        reply_markup=post_creation_keyboard()
    )

@dp.message(PostForm.waiting_for_buttons, F.text == "📚 Мои кнопки")
async def use_saved_buttons(message: types.Message, state: FSMContext):
    """Показывает сохраненные кнопки для добавления в пост"""
    buttons = get_saved_buttons(message.from_user.id)
    
    if not buttons:
        await message.answer(
            "📚 У тебя пока нет сохраненных кнопок.",
            reply_markup=post_creation_keyboard()
        )
        return
    
    # Создаем клавиатуру с кнопками для добавления
    builder = InlineKeyboardBuilder()
    for btn in buttons[:10]:  # Показываем последние 10
        builder.button(
            text=f"{btn['text'][:20]}", 
            callback_data=f"add_btn_to_post:{btn['id']}"
        )
    builder.adjust(2)
    
    # Кнопка возврата
    builder.row(types.InlineKeyboardButton(
        text="◀️ Назад", 
        callback_data="back_to_post_creation"
    ))
    
    await message.answer(
        "**Выбери кнопку для добавления в пост:**",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=builder.as_markup()
    )

@dp.callback_query(lambda c: c.data.startswith('add_btn_to_post:'))
async def add_saved_button_to_post(callback: types.CallbackQuery, state: FSMContext):
    """Добавляет сохраненную кнопку в текущий пост"""
    button_id = int(callback.data.split(':')[1])
    buttons = get_saved_buttons(callback.from_user.id)
    
    btn = next((b for b in buttons if b['id'] == button_id), None)
    if not btn:
        await callback.answer("❌ Кнопка не найдена")
        return
    
    # Получаем текущие кнопки из состояния
    data = await state.get_data()
    existing_buttons = data.get('buttons', [])
    
    # Добавляем новую кнопку
    existing_buttons.append([{'text': btn['text'], 'url': btn['url']}])
    await state.update_data(buttons=existing_buttons)
    
    # Показываем обновленный предпросмотр
    await show_preview(callback.message, state)
    
    await callback.message.delete()
    await callback.message.answer(
        f"✅ Кнопка **{btn['text']}** добавлена!\n"
        f"Можешь добавить еще или нажать **✅ Готово**",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=post_creation_keyboard()
    )
    await callback.answer()

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
    logger.info("🚀 Бот-генератор запускается...")
    await bot.delete_webhook()
    await dp.start_polling(bot)

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
