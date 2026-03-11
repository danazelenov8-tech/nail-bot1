import logging
import sqlite3
import os
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# Загружаем переменные из .env
load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')

if not BOT_TOKEN:
    print("❌ ОШИБКА: Токен бота не найден в файле .env!")
    exit()

# Получаем список админов
admin_ids_str = os.getenv('ADMIN_ID', '0')
ADMINS = []
for part in admin_ids_str.replace(',', ' ').split():
    try:
        ADMINS.append(int(part.strip()))
    except:
        pass
if not ADMINS:
    ADMINS = [0]

print(f"✅ Токен загружен")
print(f"✅ Администраторы: {ADMINS}")

# Настройки
WORK_START = 10
WORK_END = 20
LUNCH_START = 13
LUNCH_END = 14

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ========== СОСТОЯНИЯ ==========
class BookingStates(StatesGroup):
    master = State()
    service = State()
    date = State()
    time = State()
    name = State()
    phone = State()
    confirm = State()

class ScheduleStates(StatesGroup):
    edit_day = State()
    vacation = State()

class MasterStates(StatesGroup):
    name = State()
    phone = State()
    specialization = State()
    adding_photos = State()

class ServiceStates(StatesGroup):
    name = State()
    price = State()
    duration = State()
    edit_id = State()
    edit_field = State()
    edit_value = State()

class OrgSettingsStates(StatesGroup):
    edit_param = State()
    edit_value = State()

# ========== БАЗА ДАННЫХ ==========
DB_PATH = '/data/nail_studio.db' if os.path.exists('/data') else 'nail_studio.db'
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

# Удаляем старые таблицы если они есть (чтобы создать заново с правильной структурой)
cursor.execute("DROP TABLE IF EXISTS schedule")
cursor.execute("DROP TABLE IF EXISTS exceptions")
cursor.execute("DROP TABLE IF EXISTS master_photos")
cursor.execute("DROP TABLE IF EXISTS master_services")
cursor.execute("DROP TABLE IF EXISTS appointments")
cursor.execute("DROP TABLE IF EXISTS masters")
cursor.execute("DROP TABLE IF EXISTS clients")
cursor.execute("DROP TABLE IF EXISTS services")
cursor.execute("DROP TABLE IF EXISTS org_settings")
conn.commit()

# Создание таблиц заново с правильной структурой
cursor.execute('''CREATE TABLE masters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT,
    specialization TEXT,
    photo_id TEXT,
    is_active INTEGER DEFAULT 1)''')

cursor.execute('''CREATE TABLE master_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    master_id INTEGER,
    photo_id TEXT,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (master_id) REFERENCES masters (id))''')

cursor.execute('''CREATE TABLE services (
    id INTEGER PRIMARY KEY AUTOINCREMENT, 
    name TEXT, 
    price INTEGER, 
    duration INTEGER)''')

cursor.execute('''CREATE TABLE master_services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    master_id INTEGER,
    service_id INTEGER,
    FOREIGN KEY (master_id) REFERENCES masters (id),
    FOREIGN KEY (service_id) REFERENCES services (id))''')

cursor.execute('''CREATE TABLE clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT, 
    tg_id INTEGER UNIQUE, 
    name TEXT, 
    phone TEXT,
    visits INTEGER DEFAULT 0, 
    spent INTEGER DEFAULT 0)''')

cursor.execute('''CREATE TABLE appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, 
    client_id INTEGER, 
    master_id INTEGER,
    service_id INTEGER,
    date TEXT, 
    time TEXT, 
    price INTEGER,
    status TEXT DEFAULT 'active',
    reminder_24h INTEGER DEFAULT 0,
    reminder_2h INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (client_id) REFERENCES clients (id),
    FOREIGN KEY (master_id) REFERENCES masters (id),
    FOREIGN KEY (service_id) REFERENCES services (id))''')

cursor.execute('''CREATE TABLE schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    master_id INTEGER,
    day INTEGER, 
    start_time TEXT, 
    end_time TEXT, 
    is_working INTEGER DEFAULT 1,
    FOREIGN KEY (master_id) REFERENCES masters (id))''')

cursor.execute('''CREATE TABLE exceptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, 
    master_id INTEGER,
    date_from TEXT, 
    date_to TEXT, 
    reason TEXT,
    FOREIGN KEY (master_id) REFERENCES masters (id))''')

# Таблица для настроек организации
cursor.execute('''CREATE TABLE org_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    param_name TEXT UNIQUE,
    param_value TEXT)''')
conn.commit()

# Добавляем настройки по умолчанию
default_settings = [
    ("org_name", "Студия маникюра"),
    ("org_address", "ул. Ленина, 15"),
    ("org_phone", "+7 (999) 123-45-67"),
    ("org_work_hours", "10:00 - 20:00 ежедневно"),
    ("org_description", "Профессиональный маникюр и педикюр")
]

for param, value in default_settings:
    cursor.execute("INSERT OR IGNORE INTO org_settings (param_name, param_value) VALUES (?, ?)", (param, value))
conn.commit()

# Добавляем услуги
services = [
    ("Маникюр + покрытие", 1500, 60),
    ("Наращивание", 2500, 120),
    ("Дизайн", 500, 30),
    ("Снятие покрытия", 300, 20)
]
cursor.executemany("INSERT INTO services (name, price, duration) VALUES (?, ?, ?)", services)
conn.commit()

# Добавляем тестового мастера
cursor.execute("INSERT INTO masters (name, phone, specialization) VALUES (?, ?, ?)",
              ("Анна", "+7 (999) 123-45-67", "Мастер маникюра и педикюра"))
master_id = cursor.lastrowid

# Добавляем расписание для мастера
for day in range(7):
    if day < 5:
        cursor.execute("INSERT INTO schedule (master_id, day, start_time, end_time, is_working) VALUES (?, ?, '10:00', '20:00', 1)",
                      (master_id, day))
    elif day == 5:
        cursor.execute("INSERT INTO schedule (master_id, day, start_time, end_time, is_working) VALUES (?, ?, '10:00', '18:00', 1)",
                      (master_id, day))
    else:
        cursor.execute("INSERT INTO schedule (master_id, day, start_time, end_time, is_working) VALUES (?, ?, '00:00', '00:00', 0)",
                      (master_id, day))

# Добавляем все услуги мастеру
for service in cursor.execute("SELECT id FROM services").fetchall():
    cursor.execute("INSERT INTO master_services (master_id, service_id) VALUES (?, ?)",
                  (master_id, service[0]))

conn.commit()

print("✅ База данных с мастерами создана заново")

# ========== ФУНКЦИИ ==========

def get_working_hours(date_str, master_id):
    """Получить рабочие часы мастера на дату"""
    # Проверка исключений (отпуск)
    if cursor.execute("SELECT * FROM exceptions WHERE master_id = ? AND date_from <= ? AND date_to >= ?", 
                      (master_id, date_str, date_str)).fetchone():
        return []
    
    date = datetime.strptime(date_str, "%d.%m.%Y")
    day = date.weekday()
    
    # Получаем расписание мастера
    sched = cursor.execute("SELECT start_time, end_time, is_working FROM schedule WHERE master_id = ? AND day = ?", 
                          (master_id, day)).fetchone()
    if not sched or not sched[2]:
        return []
    
    slots = []
    start_h = int(sched[0].split(':')[0])
    end_h = int(sched[1].split(':')[0])
    
    for h in range(start_h, end_h):
        for m in ['00', '30']:
            if h == LUNCH_START and m == '00':
                continue
            slots.append(f"{h:02d}:{m}")
    
    return slots

def get_free_slots(date, master_id):
    """Получить свободные слоты мастера"""
    working = get_working_hours(date, master_id)
    if not working:
        return []
    
    busy = cursor.execute("SELECT time FROM appointments WHERE master_id = ? AND date = ? AND status = 'active'", 
                         (master_id, date)).fetchall()
    busy = [b[0] for b in busy]
    
    return [s for s in working if s not in busy]

def get_masters_keyboard():
    """Клавиатура с мастерами"""
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    masters = cursor.execute("SELECT id, name, specialization FROM masters WHERE is_active = 1").fetchall()
    for m in masters:
        text = f"👩‍🎨 {m[1]}"
        if m[2]:
            text += f" - {m[2]}"
        kb.inline_keyboard.append([InlineKeyboardButton(text=text, callback_data=f"master_{m[0]}")])
    return kb

def get_master_services_keyboard(master_id):
    """Клавиатура с услугами конкретного мастера"""
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    services = cursor.execute('''
        SELECT s.id, s.name, s.price 
        FROM services s
        JOIN master_services ms ON s.id = ms.service_id
        WHERE ms.master_id = ?
    ''', (master_id,)).fetchall()
    
    for s in services:
        kb.inline_keyboard.append([InlineKeyboardButton(
            text=f"{s[1]} - {s[2]}₽", 
            callback_data=f"service_{master_id}_{s[0]}"
        )])
    return kb

def get_dates_keyboard(master_id):
    """Клавиатура с датами для конкретного мастера"""
    kb = InlineKeyboardMarkup(inline_keyboard=[[]])
    today = datetime.now()
    row = []
    for i in range(14):
        date = today + timedelta(days=i)
        date_str = date.strftime("%d.%m.%Y")
        slots = get_free_slots(date_str, master_id)
        text = date.strftime("%d %b")
        if not slots:
            text = "❌ " + text
        row.append(InlineKeyboardButton(text=text, callback_data=f"date_{master_id}_{date_str}"))
        if len(row) == 3:
            kb.inline_keyboard.append(row)
            row = []
    if row:
        kb.inline_keyboard.append(row)
    return kb

def update_schedule(master_id, day, start, end, working):
    cursor.execute("UPDATE schedule SET start_time = ?, end_time = ?, is_working = ? WHERE master_id = ? AND day = ?",
                  (start, end, working, master_id, day))
    conn.commit()

def add_exception(master_id, from_date, to_date, reason):
    cursor.execute("INSERT INTO exceptions (master_id, date_from, date_to, reason) VALUES (?, ?, ?, ?)",
                  (master_id, from_date, to_date, reason))
    conn.commit()

def get_client_bonuses(tg_id):
    client = cursor.execute("SELECT id, visits, spent FROM clients WHERE tg_id = ?", (tg_id,)).fetchone()
    if client:
        return client[1], client[2]
    return 0, 0

def update_client_stats(client_id, spent_amount):
    cursor.execute("UPDATE clients SET visits = visits + 1, spent = spent + ? WHERE id = ?", (spent_amount, client_id))
    conn.commit()

def get_org_setting(param_name, default=""):
    """Получить настройку организации"""
    result = cursor.execute("SELECT param_value FROM org_settings WHERE param_name = ?", (param_name,)).fetchone()
    return result[0] if result else default

def update_org_setting(param_name, param_value):
    """Обновить настройку организации"""
    cursor.execute("UPDATE org_settings SET param_value = ? WHERE param_name = ?", (param_value, param_name))
    conn.commit()

# ========== НАПОМИНАНИЯ ==========

async def reminder_check():
    """Проверка и отправка напоминаний"""
    while True:
        try:
            now = datetime.now()
            tomorrow = (now + timedelta(days=1)).strftime("%d.%m.%Y")
            today = now.strftime("%d.%m.%Y")
            
            # Напоминания за 24 часа
            apps_24h = cursor.execute('''
                SELECT a.id, a.time, c.tg_id, c.name, s.name, m.name
                FROM appointments a
                JOIN clients c ON a.client_id = c.id
                JOIN services s ON a.service_id = s.id
                JOIN masters m ON a.master_id = m.id
                WHERE a.date = ? AND a.status = 'active' AND (a.reminder_24h = 0 OR a.reminder_24h IS NULL)
            ''', (tomorrow,)).fetchall()
            
            for app in apps_24h:
                try:
                    await bot.send_message(
                        app[2],
                        f"🔔 НАПОМИНАНИЕ ЗА 24 ЧАСА\n\n"
                        f"Завтра в {app[1]} у вас запись к мастеру {app[5]}\n"
                        f"Услуга: {app[4]}"
                    )
                    cursor.execute("UPDATE appointments SET reminder_24h = 1 WHERE id = ?", (app[0],))
                    conn.commit()
                except Exception as e:
                    print(f"Ошибка отправки напоминания 24ч: {e}")
            
            # Напоминания за 2 часа
            apps_2h = cursor.execute('''
                SELECT a.id, a.time, c.tg_id, c.name, s.name, m.name
                FROM appointments a
                JOIN clients c ON a.client_id = c.id
                JOIN services s ON a.service_id = s.id
                JOIN masters m ON a.master_id = m.id
                WHERE a.date = ? AND a.status = 'active' AND (a.reminder_2h = 0 OR a.reminder_2h IS NULL)
            ''', (today,)).fetchall()
            
            for app in apps_2h:
                try:
                    app_time = datetime.strptime(app[1], "%H:%M")
                    if (now.hour + 2) >= app_time.hour:
                        await bot.send_message(
                            app[2],
                            f"🔔 НАПОМИНАНИЕ ЗА 2 ЧАСА\n\n"
                            f"Сегодня в {app[1]} у вас запись к мастеру {app[5]}\n"
                            f"Услуга: {app[4]}"
                        )
                        cursor.execute("UPDATE appointments SET reminder_2h = 1 WHERE id = ?", (app[0],))
                        conn.commit()
                except Exception as e:
                    print(f"Ошибка отправки напоминания 2ч: {e}")
                    
            await asyncio.sleep(1800)  # 30 минут
        except Exception as e:
            print(f"Ошибка в напоминаниях: {e}")
            await asyncio.sleep(60)

# ========== КЛАВИАТУРЫ ==========

def main_keyboard():
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📅 Записаться"), KeyboardButton(text="💰 Цены")],
        [KeyboardButton(text="👩‍🎨 Наши мастера"), KeyboardButton(text="📍 Контакты")],
        [KeyboardButton(text="📋 Мои записи"), KeyboardButton(text="🎁 Мои бонусы")]
    ], resize_keyboard=True)
    return kb

def admin_keyboard():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm_stats"),
         InlineKeyboardButton(text="📅 Сегодня", callback_data="adm_today")],
        [InlineKeyboardButton(text="👥 Мастера", callback_data="adm_masters"),
         InlineKeyboardButton(text="➕ Добавить мастера", callback_data="adm_add_master")],
        [InlineKeyboardButton(text="📋 Расписание мастеров", callback_data="adm_schedule"),
         InlineKeyboardButton(text="🚫 Отпуск", callback_data="adm_vacation")],
        [InlineKeyboardButton(text="💅 Управление услугами", callback_data="adm_services"),
         InlineKeyboardButton(text="🏢 Настройки организации", callback_data="adm_org_settings")]
    ])
    return kb

def confirm_keyboard():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да", callback_data="conf_yes"),
         InlineKeyboardButton(text="❌ Нет", callback_data="conf_no")]
    ])
    return kb

def days_keyboard(master_id):
    kb = InlineKeyboardMarkup(inline_keyboard=[[]])
    days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    row = []
    for i, d in enumerate(days):
        row.append(InlineKeyboardButton(text=d, callback_data=f"day_{master_id}_{i}"))
        if len(row) == 4:
            kb.inline_keyboard.append(row)
            row = []
    if row:
        kb.inline_keyboard.append(row)
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="adm_back")])
    return kb

# ========== ОБРАБОТЧИКИ ==========

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    cursor.execute("INSERT OR IGNORE INTO clients (tg_id, name) VALUES (?, ?)",
                  (message.from_user.id, message.from_user.first_name))
    conn.commit()
    
    org_name = get_org_setting("org_name")
    
    await message.answer(
        f"👋 Добро пожаловать в **{org_name}**!\n\n"
        f"✨ **Наши возможности:**\n"
        f"• Запись к любому мастеру\n"
        f"• Портфолио работ\n"
        f"• Напоминания о записи\n"
        f"• Бонусная программа\n\n"
        f"Выберите действие в меню 👇",
        reply_markup=main_keyboard()
    )

@dp.message(F.text == "💰 Цены")
async def cmd_prices(message: types.Message):
    text = "💅 **Наши услуги:**\n\n"
    for s in cursor.execute("SELECT name, price, duration FROM services").fetchall():
        text += f"• {s[0]}: {s[1]}₽ ({s[2]} мин)\n"
    await message.answer(text)

@dp.message(F.text == "👩‍🎨 Наши мастера")
async def cmd_masters(message: types.Message):
    masters = cursor.execute("SELECT id, name, specialization FROM masters WHERE is_active = 1").fetchall()
    
    if not masters:
        await message.answer("Пока нет зарегистрированных мастеров")
        return
    
    text = "👩‍🎨 **Наши мастера:**\n\n"
    for m in masters:
        text += f"• {m[1]}\n"
        if m[2]:
            text += f"  {m[2]}\n"
        
        # Считаем количество фото
        photos_count = cursor.execute("SELECT COUNT(*) FROM master_photos WHERE master_id = ?", (m[0],)).fetchone()[0]
        if photos_count > 0:
            text += f"  📸 {photos_count} работ\n"
        text += "\n"
    
    await message.answer(text, reply_markup=get_masters_keyboard())

@dp.callback_query(lambda c: c.data.startswith('master_'))
async def show_master(callback: types.CallbackQuery):
    master_id = int(callback.data.split('_')[1])
    
    master = cursor.execute("SELECT name, phone, specialization FROM masters WHERE id = ?", (master_id,)).fetchone()
    
    text = f"👩‍🎨 **{master[0]}**\n\n"
    if master[2]:
        text += f"💬 {master[2]}\n"
    if master[1]:
        text += f"📞 {master[1]}\n\n"
    
    # Показываем фото работ
    photos = cursor.execute("SELECT id, photo_id, description FROM master_photos WHERE master_id = ? ORDER BY created_at DESC LIMIT 3", 
                           (master_id,)).fetchall()
    
    # Кнопки
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Записаться к этому мастеру", callback_data=f"book_{master_id}")]
    ])
    
    if photos:
        kb.inline_keyboard.append([InlineKeyboardButton(text="📸 Все фото работ", callback_data=f"photos_{master_id}")])
    
    await callback.message.answer(text, reply_markup=kb)
    
    # Отправляем фото (первые 3)
    for p in photos[:3]:
        try:
            await bot.send_photo(
                chat_id=callback.message.chat.id,
                photo=p[1],
                caption=p[2] if p[2] else "Работа мастера"
            )
        except:
            pass
    
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith('photos_'))
async def show_all_photos(callback: types.CallbackQuery):
    master_id = int(callback.data.split('_')[1])
    
    photos = cursor.execute("SELECT photo_id, description FROM master_photos WHERE master_id = ? ORDER BY created_at DESC", 
                           (master_id,)).fetchall()
    
    if not photos:
        await callback.message.answer("У этого мастера пока нет фото работ")
        await callback.answer()
        return
    
    await callback.message.answer(f"📸 **Всего работ:** {len(photos)}")
    
    for p in photos[:10]:  # Показываем последние 10
        try:
            await bot.send_photo(
                chat_id=callback.message.chat.id,
                photo=p[0],
                caption=p[1] if p[1] else "Работа мастера"
            )
            await asyncio.sleep(0.5)  # Небольшая задержка
        except:
            pass
    
    await callback.answer()

@dp.message(F.text == "📍 Контакты")
async def cmd_contacts(message: types.Message):
    org_name = get_org_setting("org_name")
    org_address = get_org_setting("org_address")
    org_phone = get_org_setting("org_phone")
    org_work_hours = get_org_setting("org_work_hours")
    org_description = get_org_setting("org_description")
    
    await message.answer(
        f"🏢 **{org_name}**\n\n"
        f"📍 **Адрес:** {org_address}\n"
        f"📞 **Телефон:** {org_phone}\n"
        f"⏰ **Режим работы:** {org_work_hours}\n\n"
        f"📝 **О нас:** {org_description}"
    )

@dp.message(F.text == "📋 Мои записи")
async def cmd_my_apps(message: types.Message):
    apps = cursor.execute('''
        SELECT a.date, a.time, m.name, s.name, a.price, a.id
        FROM appointments a
        JOIN clients c ON a.client_id = c.id
        JOIN masters m ON a.master_id = m.id
        JOIN services s ON a.service_id = s.id
        WHERE c.tg_id = ? AND a.status = 'active'
        ORDER BY a.date
    ''', (message.from_user.id,)).fetchall()
    
    if not apps:
        await message.answer("У вас нет активных записей")
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for a in apps:
        kb.inline_keyboard.append([InlineKeyboardButton(
            text=f"{a[0]} {a[1]} - {a[2]} ({a[3]})",
            callback_data=f"app_{a[5]}"
        )])
    
    await message.answer("📋 **Ваши записи:**", reply_markup=kb)

@dp.message(F.text == "🎁 Мои бонусы")
async def cmd_bonuses(message: types.Message):
    visits, spent = get_client_bonuses(message.from_user.id)
    next_discount = 10 - (visits % 10)
    
    text = (
        "🎁 **БОНУСНАЯ ПРОГРАММА**\n\n"
        f"✅ **Посещений:** {visits}\n"
        f"💰 **Потрачено:** {spent}₽\n"
        f"💎 **Скидка:** {(visits // 10) * 5}%\n"
        f"🔜 **До следующей скидки:** {next_discount} посещений"
    )
    await message.answer(text)

@dp.message(F.text == "📅 Записаться")
async def cmd_book_start(message: types.Message, state: FSMContext):
    await state.clear()
    masters = cursor.execute("SELECT COUNT(*) FROM masters WHERE is_active = 1").fetchone()[0]
    
    if masters == 0:
        await message.answer("Извините, сейчас нет доступных мастеров")
        return
    
    await message.answer("Выберите мастера:", reply_markup=get_masters_keyboard())
    await state.set_state(BookingStates.master)

# ========== ПРОЦЕСС ЗАПИСИ ==========

@dp.callback_query(lambda c: c.data.startswith('book_') or c.data.startswith('master_'), BookingStates.master)
async def process_master_selection(callback: types.CallbackQuery, state: FSMContext):
    # Извлекаем master_id из разных форматов callback_data
    if callback.data.startswith('book_'):
        master_id = int(callback.data.split('_')[1])
    else:
        master_id = int(callback.data.split('_')[1])
    
    await state.update_data(master_id=master_id)
    
    master = cursor.execute("SELECT name FROM masters WHERE id = ?", (master_id,)).fetchone()
    await state.update_data(master_name=master[0])
    
    await callback.message.edit_text(
        f"Вы выбрали мастера {master[0]}\n\nТеперь выберите услугу:",
        reply_markup=get_master_services_keyboard(master_id)
    )
    await state.set_state(BookingStates.service)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith('service_'), BookingStates.service)
async def process_service(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split('_')
    master_id = int(parts[1])
    service_id = int(parts[2])
    
    await state.update_data(service_id=service_id)
    
    service = cursor.execute("SELECT name, price FROM services WHERE id = ?", (service_id,)).fetchone()
    await state.update_data(service_name=service[0], service_price=service[1])
    
    await callback.message.edit_text(
        f"Выбрана услуга: {service[0]}\n\nТеперь выберите дату:",
        reply_markup=get_dates_keyboard(master_id)
    )
    await state.set_state(BookingStates.date)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith('date_'), BookingStates.date)
async def process_date(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split('_')
    master_id = int(parts[1])
    date = parts[2]
    
    data = await state.get_data()
    slots = get_free_slots(date, master_id)
    
    if not slots:
        await callback.message.edit_text(
            "Нет свободных слотов. Выберите другую дату:",
            reply_markup=get_dates_keyboard(master_id)
        )
        await callback.answer()
        return
    
    await state.update_data(date=date)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[]])
    row = []
    for s in slots[:12]:
        row.append(InlineKeyboardButton(text=s, callback_data=f"time_{s}"))
        if len(row) == 3:
            kb.inline_keyboard.append(row)
            row = []
    if row:
        kb.inline_keyboard.append(row)
    
    await callback.message.edit_text(f"Выберите время на {date}:", reply_markup=kb)
    await state.set_state(BookingStates.time)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith('time_'), BookingStates.time)
async def process_time(callback: types.CallbackQuery, state: FSMContext):
    time = callback.data.split('_')[1]
    await state.update_data(time=time)
    
    await callback.message.edit_text("Введите ваше имя:")
    await state.set_state(BookingStates.name)
    await callback.answer()

@dp.message(BookingStates.name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введите номер телефона:")
    await state.set_state(BookingStates.phone)

@dp.message(BookingStates.phone)
async def process_phone(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.text)
    data = await state.get_data()
    
    await message.answer(
        f"📝 **Проверьте данные:**\n\n"
        f"**Мастер:** {data['master_name']}\n"
        f"**Услуга:** {data['service_name']}\n"
        f"**Дата:** {data['date']}\n"
        f"**Время:** {data['time']}\n"
        f"**Имя:** {data['name']}\n"
        f"**Телефон:** {data['phone']}\n"
        f"**Сумма:** {data['service_price']}₽\n\n"
        f"✅ После подтверждения придёт напоминание",
        reply_markup=confirm_keyboard()
    )
    await state.set_state(BookingStates.confirm)

@dp.callback_query(lambda c: c.data == "conf_yes", BookingStates.confirm)
async def process_confirm(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    
    client = cursor.execute("SELECT id FROM clients WHERE tg_id = ?", (callback.from_user.id,)).fetchone()
    
    if not client:
        cursor.execute("INSERT INTO clients (tg_id, name, phone) VALUES (?, ?, ?)",
                      (callback.from_user.id, data['name'], data['phone']))
        client_id = cursor.lastrowid
    else:
        client_id = client[0]
    
    cursor.execute('''
        INSERT INTO appointments (client_id, master_id, service_id, date, time, price)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (client_id, data['master_id'], data['service_id'], data['date'], data['time'], data['service_price']))
    conn.commit()
    
    update_client_stats(client_id, data['service_price'])
    
    await callback.message.edit_text(
        "✅ **ЗАПИСЬ ПОДТВЕРЖДЕНА!**\n\n"
        f"👩‍🎨 **Мастер:** {data['master_name']}\n"
        f"💅 **Услуга:** {data['service_name']}\n"
        f"📍 **{data['date']}** в **{data['time']}**\n"
        f"💵 **{data['service_price']}₽**\n\n"
        "🔔 Напоминания придут за 24 и 2 часа до записи"
    )
    
    # Уведомление админам
    for admin_id in ADMINS:
        try:
            await bot.send_message(
                admin_id,
                f"🔔 **НОВАЯ ЗАПИСЬ!**\n\n"
                f"**Клиент:** {data['name']}\n"
                f"**Тел:** {data['phone']}\n"
                f"**Мастер:** {data['master_name']}\n"
                f"**Услуга:** {data['service_name']}\n"
                f"**Дата:** {data['date']} {data['time']}"
            )
        except:
            pass
    
    await state.clear()
    await callback.answer()

@dp.callback_query(lambda c: c.data == "conf_no", BookingStates.confirm)
async def process_cancel(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("❌ Запись отменена")
    await state.clear()
    await callback.answer()

# ========== АДМИНКА ==========

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id not in ADMINS:
        await message.answer("⛔ Доступ запрещен")
        return
    
    await message.answer("🔧 **ПАНЕЛЬ АДМИНИСТРАТОРА**", reply_markup=admin_keyboard())

@dp.callback_query(lambda c: c.data == "adm_stats")
async def admin_stats(callback: types.CallbackQuery):
    today = datetime.now().strftime("%d.%m.%Y")
    month_start = datetime.now().replace(day=1).strftime("%d.%m.%Y")
    
    t_count = cursor.execute("SELECT COUNT(*) FROM appointments WHERE date = ? AND status = 'active'", (today,)).fetchone()[0]
    t_sum = cursor.execute("SELECT SUM(price) FROM appointments WHERE date = ? AND status = 'active'", (today,)).fetchone()[0] or 0
    
    m_count = cursor.execute("SELECT COUNT(*) FROM appointments WHERE date >= ? AND status = 'active'", (month_start,)).fetchone()[0]
    m_sum = cursor.execute("SELECT SUM(price) FROM appointments WHERE date >= ? AND status = 'active'", (month_start,)).fetchone()[0] or 0
    
    total_clients = cursor.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
    total_masters = cursor.execute("SELECT COUNT(*) FROM masters").fetchone()[0]
    
    text = (
        "📊 **СТАТИСТИКА**\n\n"
        f"📅 **Сегодня:**\n"
        f"   Записей: {t_count}\n"
        f"   Выручка: {t_sum}₽\n\n"
        f"📆 **За месяц:**\n"
        f"   Записей: {m_count}\n"
        f"   Выручка: {m_sum}₽\n\n"
        f"👥 **Всего клиентов:** {total_clients}\n"
        f"👩‍🎨 **Мастеров:** {total_masters}"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="adm_back")]])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "adm_today")
async def admin_today(callback: types.CallbackQuery):
    today = datetime.now().strftime("%d.%m.%Y")
    apps = cursor.execute('''
        SELECT a.time, c.name, c.phone, s.name, m.name
        FROM appointments a
        JOIN clients c ON a.client_id = c.id
        JOIN services s ON a.service_id = s.id
        JOIN masters m ON a.master_id = m.id
        WHERE a.date = ? AND a.status = 'active'
        ORDER BY a.time
    ''', (today,)).fetchall()
    
    if not apps:
        text = "На сегодня записей нет"
    else:
        text = "📅 **ЗАПИСИ НА СЕГОДНЯ**\n\n"
        for a in apps:
            text += f"⏰ {a[0]} - {a[1]}\n📞 {a[2]}\n💅 {a[3]}\n👩‍🎨 {a[4]}\n\n"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="adm_back")]])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "adm_masters")
async def admin_masters(callback: types.CallbackQuery):
    masters = cursor.execute('''
        SELECT id, name, phone, specialization, 
               (SELECT COUNT(*) FROM master_photos WHERE master_id = masters.id) as photos_count
        FROM masters WHERE is_active = 1
    ''').fetchall()
    
    if not masters:
        text = "Нет зарегистрированных мастеров"
    else:
        text = "👩‍🎨 **МАСТЕРА:**\n\n"
        for m in masters:
            text += f"• {m[1]}\n"
            if m[3]:
                text += f"  💬 {m[3]}\n"
            if m[2]:
                text += f"  📞 {m[2]}\n"
            text += f"  📸 Фото работ: {m[4]}\n\n"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить мастера", callback_data="adm_add_master")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_back")]
    ])
    
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "adm_add_master")
async def admin_add_master(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Введите имя нового мастера:"
    )
    await state.set_state(MasterStates.name)
    await callback.answer()

@dp.message(MasterStates.name)
async def master_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введите специализацию мастера (что делает):")
    await state.set_state(MasterStates.phone)

@dp.message(MasterStates.phone)
async def master_specialization(message: types.Message, state: FSMContext):
    await state.update_data(specialization=message.text)
    await message.answer("Введите телефон мастера (можно пропустить, отправьте '-'):")
    await state.set_state(MasterStates.adding_photos)

@dp.message(MasterStates.adding_photos)
async def master_phone(message: types.Message, state: FSMContext):
    phone = message.text if message.text != '-' else None
    data = await state.get_data()
    
    cursor.execute('''
        INSERT INTO masters (name, phone, specialization)
        VALUES (?, ?, ?)
    ''', (data['name'], phone, data['specialization']))
    
    master_id = cursor.lastrowid
    
    # Добавляем стандартное расписание
    for day in range(7):
        if day < 5:
            cursor.execute("INSERT INTO schedule (master_id, day, start_time, end_time, is_working) VALUES (?, ?, '10:00', '20:00', 1)",
                          (master_id, day))
        elif day == 5:
            cursor.execute("INSERT INTO schedule (master_id, day, start_time, end_time, is_working) VALUES (?, ?, '10:00', '18:00', 1)",
                          (master_id, day))
        else:
            cursor.execute("INSERT INTO schedule (master_id, day, start_time, end_time, is_working) VALUES (?, ?, '00:00', '00:00', 0)",
                          (master_id, day))
    
    # Добавляем все услуги мастеру
    for service in cursor.execute("SELECT id FROM services").fetchall():
        cursor.execute("INSERT INTO master_services (master_id, service_id) VALUES (?, ?)",
                      (master_id, service[0]))
    
    conn.commit()
    
    await message.answer(f"✅ Мастер {data['name']} успешно добавлен!")
    await state.clear()
    await message.answer("Что дальше?", reply_markup=admin_keyboard())

@dp.message(F.photo)
async def add_master_photo(message: types.Message, state: FSMContext):
    # Проверяем, не в процессе ли добавления фото
    current_state = await state.get_state()
    if current_state != MasterStates.adding_photos.state:
        return
    
    data = await state.get_data()
    master_id = data.get('master_id')
    
    if not master_id:
        return
    
    photo = message.photo[-1]
    
    cursor.execute('''
        INSERT INTO master_photos (master_id, photo_id, description)
        VALUES (?, ?, ?)
    ''', (master_id, photo.file_id, message.caption if message.caption else None))
    
    conn.commit()
    
    await message.answer("✅ Фото добавлено! Отправьте следующее или /done для завершения")

@dp.message(Command("done"))
async def done_adding_photos(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("✅ Добавление фото завершено!", reply_markup=main_keyboard())

@dp.callback_query(lambda c: c.data == "adm_schedule")
async def admin_schedule(callback: types.CallbackQuery):
    masters = cursor.execute("SELECT id, name FROM masters WHERE is_active = 1").fetchall()
    
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for m in masters:
        kb.inline_keyboard.append([InlineKeyboardButton(text=m[1], callback_data=f"master_sched_{m[0]}")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="adm_back")])
    
    await callback.message.edit_text("Выберите мастера для просмотра расписания:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith('master_sched_'))
async def master_schedule(callback: types.CallbackQuery):
    master_id = int(callback.data.split('_')[2])
    
    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    sched = cursor.execute("SELECT day, start_time, end_time, is_working FROM schedule WHERE master_id = ? ORDER BY day", 
                          (master_id,)).fetchall()
    
    master = cursor.execute("SELECT name FROM masters WHERE id = ?", (master_id,)).fetchone()
    
    text = f"👩‍🎨 **Расписание мастера {master[0]}**\n\n"
    for s in sched:
        if s[3]:
            text += f"{days[s[0]]}: {s[1]} - {s[2]}\n"
        else:
            text += f"{days[s[0]]}: Выходной\n"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_sched_{master_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_schedule")]
    ])
    
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith('edit_sched_'))
async def edit_schedule(callback: types.CallbackQuery, state: FSMContext):
    master_id = int(callback.data.split('_')[2])
    await state.update_data(edit_master_id=master_id)
    
    await callback.message.edit_text(
        "Выберите день для редактирования:",
        reply_markup=days_keyboard(master_id)
    )
    await ScheduleStates.edit_day.set()
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith('day_'), ScheduleStates.edit_day)
async def process_edit_day(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split('_')
    master_id = int(parts[1])
    day = int(parts[2])
    
    await state.update_data(edit_day=day, edit_master_id=master_id)
    
    sched = cursor.execute("SELECT start_time, end_time, is_working FROM schedule WHERE master_id = ? AND day = ?", 
                          (master_id, day)).fetchone()
    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    
    if sched[2]:
        text = f"{days[day]}\nТекущее: {sched[0]} - {sched[1]}\n\nВведите новое время (10:00-18:00) или 'выходной'"
    else:
        text = f"{days[day]}\nТекущее: Выходной\n\nВведите время (10:00-18:00) или 'выходной'"
    
    await callback.message.edit_text(text)
    await ScheduleStates.edit_day.set()
    await callback.answer()

@dp.message(ScheduleStates.edit_day)
async def save_schedule(message: types.Message, state: FSMContext):
    data = await state.get_data()
    master_id = data['edit_master_id']
    day = data['edit_day']
    text = message.text.lower().strip()
    
    if text == 'выходной':
        update_schedule(master_id, day, "00:00", "00:00", 0)
        await message.answer("✅ День установлен как выходной")
    else:
        try:
            times = text.split('-')
            start = times[0].strip()
            end = times[1].strip()
            if len(start) == 5 and len(end) == 5:
                update_schedule(master_id, day, start, end, 1)
                await message.answer(f"✅ Установлено: {start} - {end}")
            else:
                await message.answer("❌ Неверный формат")
        except:
            await message.answer("❌ Ошибка формата")
    
    await state.clear()
    await message.answer("Что дальше?", reply_markup=admin_keyboard())

@dp.callback_query(lambda c: c.data == "adm_vacation")
async def admin_vacation(callback: types.CallbackQuery):
    masters = cursor.execute("SELECT id, name FROM masters WHERE is_active = 1").fetchall()
    
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for m in masters:
        kb.inline_keyboard.append([InlineKeyboardButton(text=m[1], callback_data=f"vac_master_{m[0]}")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="adm_back")])
    
    await callback.message.edit_text("Выберите мастера для отпуска:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith('vac_master_'))
async def process_vacation_master(callback: types.CallbackQuery, state: FSMContext):
    master_id = int(callback.data.split('_')[2])
    await state.update_data(vac_master_id=master_id)
    
    await callback.message.edit_text(
        "Введите даты отпуска (ДД.ММ.ГГГГ-ДД.ММ.ГГГГ):\n"
        "Пример: 01.06.2024-10.06.2024"
    )
    await ScheduleStates.vacation.set()
    await callback.answer()

@dp.message(ScheduleStates.vacation)
async def save_vacation(message: types.Message, state: FSMContext):
    data = await state.get_data()
    master_id = data['vac_master_id']
    
    try:
        dates = message.text.split('-')
        date_from = dates[0].strip()
        date_to = dates[1].strip()
        
        datetime.strptime(date_from, "%d.%m.%Y")
        datetime.strptime(date_to, "%d.%m.%Y")
        
        add_exception(master_id, date_from, date_to, "Отпуск")
        
        master = cursor.execute("SELECT name FROM masters WHERE id = ?", (master_id,)).fetchone()
        await message.answer(f"✅ Отпуск для {master[0]} добавлен с {date_from} по {date_to}")
    except:
        await message.answer("❌ Ошибка формата")
    
    await state.clear()
    await message.answer("Что дальше?", reply_markup=admin_keyboard())

# ========== УПРАВЛЕНИЕ УСЛУГАМИ ==========

@dp.callback_query(lambda c: c.data == "adm_services")
async def admin_services(callback: types.CallbackQuery):
    services = cursor.execute("SELECT id, name, price, duration FROM services").fetchall()
    
    text = "💅 **УПРАВЛЕНИЕ УСЛУГАМИ**\n\n"
    for s in services:
        text += f"• {s[1]}: {s[2]}₽ ({s[3]} мин)\n"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить услугу", callback_data="adm_add_service")],
        [InlineKeyboardButton(text="✏️ Редактировать услугу", callback_data="adm_edit_service")],
        [InlineKeyboardButton(text="❌ Удалить услугу", callback_data="adm_delete_service")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_back")]
    ])
    
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "adm_add_service")
async def add_service_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Введите название новой услуги:"
    )
    await state.set_state(ServiceStates.name)
    await callback.answer()

@dp.message(ServiceStates.name)
async def add_service_name(message: types.Message, state: FSMContext):
    await state.update_data(service_name=message.text)
    await message.answer("Введите цену услуги (только число):")
    await state.set_state(ServiceStates.price)

@dp.message(ServiceStates.price)
async def add_service_price(message: types.Message, state: FSMContext):
    try:
        price = int(message.text)
        await state.update_data(service_price=price)
        await message.answer("Введите длительность услуги в минутах (только число):")
        await state.set_state(ServiceStates.duration)
    except:
        await message.answer("❌ Ошибка! Введите число, например: 1500")
        return

@dp.message(ServiceStates.duration)
async def add_service_duration(message: types.Message, state: FSMContext):
    try:
        duration = int(message.text)
        data = await state.get_data()
        
        cursor.execute('''
            INSERT INTO services (name, price, duration)
            VALUES (?, ?, ?)
        ''', (data['service_name'], data['service_price'], duration))
        conn.commit()
        
        # Добавляем услугу всем мастерам
        masters = cursor.execute("SELECT id FROM masters").fetchall()
        service_id = cursor.lastrowid
        for master in masters:
            cursor.execute("INSERT INTO master_services (master_id, service_id) VALUES (?, ?)",
                          (master[0], service_id))
        conn.commit()
        
        await message.answer(f"✅ Услуга '{data['service_name']}' успешно добавлена!")
        await state.clear()
        await message.answer("Что дальше?", reply_markup=admin_keyboard())
    except:
        await message.answer("❌ Ошибка! Введите число, например: 60")
        return

@dp.callback_query(lambda c: c.data == "adm_edit_service")
async def edit_service_list(callback: types.CallbackQuery):
    services = cursor.execute("SELECT id, name, price, duration FROM services").fetchall()
    
    if not services:
        await callback.message.edit_text("Нет доступных услуг для редактирования")
        await callback.answer()
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for s in services:
        kb.inline_keyboard.append([InlineKeyboardButton(
            text=f"{s[1]} - {s[2]}₽", 
            callback_data=f"edit_service_{s[0]}"
        )])
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="adm_services")])
    
    await callback.message.edit_text("Выберите услугу для редактирования:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith('edit_service_'))
async def edit_service_menu(callback: types.CallbackQuery, state: FSMContext):
    service_id = int(callback.data.split('_')[2])
    await state.update_data(edit_service_id=service_id)
    
    service = cursor.execute("SELECT name, price, duration FROM services WHERE id = ?", (service_id,)).fetchone()
    
    text = f"✏️ **Редактирование услуги**\n\n"
    text += f"Текущие данные:\n"
    text += f"• Название: {service[0]}\n"
    text += f"• Цена: {service[1]}₽\n"
    text += f"• Длительность: {service[2]} мин\n\n"
    text += "Что хотите изменить?"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Название", callback_data="edit_service_field_name")],
        [InlineKeyboardButton(text="💰 Цену", callback_data="edit_service_field_price")],
        [InlineKeyboardButton(text="⏱ Длительность", callback_data="edit_service_field_duration")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_services")]
    ])
    
    await callback.message.edit_text(text, reply_markup=kb)
    await ServiceStates.edit_field.set()
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith('edit_service_field_'), ServiceStates.edit_field)
async def edit_service_field(callback: types.CallbackQuery, state: FSMContext):
    field = callback.data.replace('edit_service_field_', '')
    await state.update_data(edit_field=field)
    
    prompts = {
        'name': "Введите новое название услуги:",
        'price': "Введите новую цену (только число):",
        'duration': "Введите новую длительность в минутах (только число):"
    }
    
    await callback.message.edit_text(prompts.get(field, "Введите новое значение:"))
    await ServiceStates.edit_value.set()
    await callback.answer()

@dp.message(ServiceStates.edit_value)
async def edit_service_value(message: types.Message, state: FSMContext):
    data = await state.get_data()
    service_id = data['edit_service_id']
    field = data['edit_field']
    
    try:
        if field == 'name':
            cursor.execute("UPDATE services SET name = ? WHERE id = ?", (message.text, service_id))
            conn.commit()
            await message.answer(f"✅ Название услуги изменено на '{message.text}'")
        
        elif field == 'price':
            price = int(message.text)
            cursor.execute("UPDATE services SET price = ? WHERE id = ?", (price, service_id))
            conn.commit()
            await message.answer(f"✅ Цена услуги изменена на {price}₽")
        
        elif field == 'duration':
            duration = int(message.text)
            cursor.execute("UPDATE services SET duration = ? WHERE id = ?", (duration, service_id))
            conn.commit()
            await message.answer(f"✅ Длительность услуги изменена на {duration} мин")
        
        await state.clear()
        await message.answer("Что дальше?", reply_markup=admin_keyboard())
        
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}. Попробуйте снова.")
        await state.clear()

@dp.callback_query(lambda c: c.data == "adm_delete_service")
async def delete_service_list(callback: types.CallbackQuery):
    services = cursor.execute("SELECT id, name, price FROM services").fetchall()
    
    if not services:
        await callback.message.edit_text("Нет доступных услуг для удаления")
        await callback.answer()
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for s in services:
        kb.inline_keyboard.append([InlineKeyboardButton(
            text=f"❌ {s[1]} - {s[2]}₽", 
            callback_data=f"delete_service_{s[0]}"
        )])
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="adm_services")])
    
    await callback.message.edit_text("Выберите услугу для удаления:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith('delete_service_'))
async def delete_service_confirm(callback: types.CallbackQuery):
    service_id = int(callback.data.split('_')[2])
    
    # Проверяем, есть ли записи с этой услугой
    appointments = cursor.execute("SELECT COUNT(*) FROM appointments WHERE service_id = ?", (service_id,)).fetchone()[0]
    
    if appointments > 0:
        await callback.message.edit_text(
            f"❌ Нельзя удалить услугу, так как есть {appointments} записей с ней.\n"
            f"Сначала отмените или завершите эти записи."
        )
        await callback.answer()
        return
    
    # Удаляем связь с мастерами
    cursor.execute("DELETE FROM master_services WHERE service_id = ?", (service_id,))
    # Удаляем услугу
    cursor.execute("DELETE FROM services WHERE id = ?", (service_id,))
    conn.commit()
    
    await callback.message.edit_text("✅ Услуга успешно удалена!")
    await callback.answer()

# ========== НАСТРОЙКИ ОРГАНИЗАЦИИ ==========

@dp.callback_query(lambda c: c.data == "adm_org_settings")
async def org_settings_menu(callback: types.CallbackQuery):
    org_name = get_org_setting("org_name")
    org_address = get_org_setting("org_address")
    org_phone = get_org_setting("org_phone")
    org_work_hours = get_org_setting("org_work_hours")
    org_description = get_org_setting("org_description")
    
    text = (
        f"🏢 **НАСТРОЙКИ ОРГАНИЗАЦИИ**\n\n"
        f"📌 **Название:** {org_name}\n"
        f"📍 **Адрес:** {org_address}\n"
        f"📞 **Телефон:** {org_phone}\n"
        f"⏰ **Режим работы:** {org_work_hours}\n"
        f"📝 **Описание:** {org_description}\n\n"
        f"Выберите, что хотите изменить:"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📌 Название", callback_data="org_edit_name"),
         InlineKeyboardButton(text="📍 Адрес", callback_data="org_edit_address")],
        [InlineKeyboardButton(text="📞 Телефон", callback_data="org_edit_phone"),
         InlineKeyboardButton(text="⏰ Режим работы", callback_data="org_edit_hours")],
        [InlineKeyboardButton(text="📝 Описание", callback_data="org_edit_description")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_back")]
    ])
    
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith('org_edit_'))
async def org_edit_start(callback: types.CallbackQuery, state: FSMContext):
    param = callback.data.replace('org_edit_', '')
    
    param_names = {
        'name': 'название организации',
        'address': 'адрес',
        'phone': 'телефон',
        'hours': 'режим работы',
        'description': 'описание'
    }
    
    param_values = {
        'name': get_org_setting("org_name"),
        'address': get_org_setting("org_address"),
        'phone': get_org_setting("org_phone"),
        'hours': get_org_setting("org_work_hours"),
        'description': get_org_setting("org_description")
    }
    
    await state.update_data(edit_param=param)
    
    text = (
        f"✏️ **Редактирование {param_names.get(param, 'параметра')}**\n\n"
        f"Текущее значение:\n"
        f"`{param_values.get(param, '')}`\n\n"
        f"Введите новое значение:"
    )
    
    await callback.message.edit_text(text)
    await OrgSettingsStates.edit_value.set()
    await callback.answer()

@dp.message(OrgSettingsStates.edit_value)
async def org_edit_value(message: types.Message, state: FSMContext):
    data = await state.get_data()
    param = data['edit_param']
    
    param_db = {
        'name': 'org_name',
        'address': 'org_address',
        'phone': 'org_phone',
        'hours': 'org_work_hours',
        'description': 'org_description'
    }
    
    param_names = {
        'name': 'Название',
        'address': 'Адрес',
        'phone': 'Телефон',
        'hours': 'Режим работы',
        'description': 'Описание'
    }
    
    db_param = param_db.get(param)
    if db_param:
        update_org_setting(db_param, message.text)
        await message.answer(f"✅ {param_names.get(param, 'Параметр')} успешно обновлено!")
    
    await state.clear()
    await message.answer("Что дальше?", reply_markup=admin_keyboard())

@dp.callback_query(lambda c: c.data == "adm_back")
async def admin_back(callback: types.CallbackQuery):
    await callback.message.edit_text("🔧 **ПАНЕЛЬ АДМИНИСТРАТОРА**", reply_markup=admin_keyboard())
    await callback.answer()

# ========== ОТМЕНА ЗАПИСИ ==========

@dp.callback_query(lambda c: c.data.startswith('app_'))
async def cancel_app(callback: types.CallbackQuery):
    app_id = int(callback.data.split('_')[1])
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить отмену", callback_data=f"del_{app_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_apps")]
    ])
    
    await callback.message.edit_text("❓ Отменить запись?", reply_markup=kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith('del_'))
async def confirm_cancel(callback: types.CallbackQuery):
    app_id = int(callback.data.split('_')[1])
    
    app_info = cursor.execute('''
        SELECT c.name, c.phone, a.date, a.time, m.name
        FROM appointments a
        JOIN clients c ON a.client_id = c.id
        JOIN masters m ON a.master_id = m.id
        WHERE a.id = ?
    ''', (app_id,)).fetchone()
    
    cursor.execute("UPDATE appointments SET status = 'cancelled' WHERE id = ?", (app_id,))
    conn.commit()
    
    await callback.message.edit_text("✅ Запись отменена")
    
    for admin_id in ADMINS:
        try:
            await bot.send_message(
                admin_id,
                f"❌ **ОТМЕНА ЗАПИСИ**\n\n"
                f"**Клиент:** {app_info[0]}\n"
                f"**Тел:** {app_info[1]}\n"
                f"**Мастер:** {app_info[4]}\n"
                f"**Дата:** {app_info[2]} {app_info[3]}"
            )
        except:
            pass
    
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_to_apps")
async def back_to_apps(callback: types.CallbackQuery):
    apps = cursor.execute('''
        SELECT a.date, a.time, m.name, s.name, a.price, a.id
        FROM appointments a
        JOIN clients c ON a.client_id = c.id
        JOIN masters m ON a.master_id = m.id
        JOIN services s ON a.service_id = s.id
        WHERE c.tg_id = ? AND a.status = 'active'
        ORDER BY a.date
    ''', (callback.from_user.id,)).fetchall()
    
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for a in apps:
        kb.inline_keyboard.append([InlineKeyboardButton(
            text=f"{a[0]} {a[1]} - {a[2]} ({a[3]})",
            callback_data=f"app_{a[5]}"
        )])
    
    await callback.message.edit_text("📋 **Ваши записи:**", reply_markup=kb)
    await callback.answer()

# Команда отмены
@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено", reply_markup=main_keyboard())

# ========== ЗАПУСК ==========

async def on_startup():
    asyncio.create_task(reminder_check())
    print("✅ Планировщик напоминаний запущен")

async def main():
    await on_startup()
    await dp.start_polling(bot)

if __name__ == '__main__':
    print("🚀 БОТ С ПОЛНЫМИ НАСТРОЙКАМИ ЗАПУСКАЕТСЯ...")
    print(f"👑 Администраторы: {ADMINS}")
    print(f"📁 База данных: {DB_PATH}")
    asyncio.run(main())