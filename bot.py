import logging
import sqlite3
import os
import asyncio
from datetime import datetime, timedelta
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, executor
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.contrib.middlewares.logging import LoggingMiddleware

# Загружаем переменные
load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')

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

if not BOT_TOKEN:
    print("❌ ОШИБКА: Токен не найден в файле .env!")
    exit()

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
dp = Dispatcher(bot, storage=storage)
dp.middleware.setup(LoggingMiddleware())

# ========== СОСТОЯНИЯ ==========
class BookingStates(StatesGroup):
    service = State()
    date = State()
    time = State()
    name = State()
    phone = State()
    confirm = State()

class ScheduleStates(StatesGroup):
    edit_day = State()
    vacation = State()

# ========== БАЗА ДАННЫХ ==========
# Для сервера используем путь /data, чтобы данные не терялись
DB_PATH = '/data/nail_studio.db' if os.path.exists('/data') else 'nail_studio.db'
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

# Создание таблиц
cursor.execute('''CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY AUTOINCREMENT, 
    name TEXT, 
    price INTEGER, 
    duration INTEGER)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT, 
    tg_id INTEGER UNIQUE, 
    name TEXT, 
    phone TEXT,
    visits INTEGER DEFAULT 0, 
    spent INTEGER DEFAULT 0)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, 
    client_id INTEGER, 
    service_id INTEGER,
    date TEXT, 
    time TEXT, 
    price INTEGER,
    status TEXT DEFAULT 'active',
    reminder_24h INTEGER DEFAULT 0,
    reminder_2h INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (client_id) REFERENCES clients (id),
    FOREIGN KEY (service_id) REFERENCES services (id))''')

cursor.execute('''CREATE TABLE IF NOT EXISTS schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day INTEGER, 
    start_time TEXT, 
    end_time TEXT, 
    is_working INTEGER DEFAULT 1)''')

cursor.execute('''CREATE TABLE IF NOT EXISTS exceptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, 
    date_from TEXT, 
    date_to TEXT, 
    reason TEXT)''')
conn.commit()

# Добавляем услуги
if cursor.execute("SELECT COUNT(*) FROM services").fetchone()[0] == 0:
    services = [
        ("Маникюр + покрытие", 1500, 60),
        ("Наращивание", 2500, 120),
        ("Дизайн", 500, 30),
        ("Снятие покрытия", 300, 20)
    ]
    cursor.executemany("INSERT INTO services (name, price, duration) VALUES (?, ?, ?)", services)
    conn.commit()

# Добавляем расписание
if cursor.execute("SELECT COUNT(*) FROM schedule").fetchone()[0] == 0:
    for day in range(5):
        cursor.execute("INSERT INTO schedule (day, start_time, end_time, is_working) VALUES (?, '10:00', '20:00', 1)", (day,))
    cursor.execute("INSERT INTO schedule (day, start_time, end_time, is_working) VALUES (5, '10:00', '18:00', 1)")
    cursor.execute("INSERT INTO schedule (day, start_time, end_time, is_working) VALUES (6, '00:00', '00:00', 0)")
    conn.commit()

print("✅ База данных готова")

# ========== ФУНКЦИИ ==========

def get_working_hours(date_str):
    if cursor.execute("SELECT * FROM exceptions WHERE date_from <= ? AND date_to >= ?", (date_str, date_str)).fetchone():
        return []
    
    date = datetime.strptime(date_str, "%d.%m.%Y")
    day = date.weekday()
    
    sched = cursor.execute("SELECT start_time, end_time, is_working FROM schedule WHERE day = ?", (day,)).fetchone()
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

def get_free_slots(date):
    working = get_working_hours(date)
    if not working:
        return []
    
    busy = cursor.execute("SELECT time FROM appointments WHERE date = ? AND status = 'active'", (date,)).fetchall()
    busy = [b[0] for b in busy]
    
    return [s for s in working if s not in busy]

def update_schedule(day, start, end, working):
    cursor.execute("UPDATE schedule SET start_time = ?, end_time = ?, is_working = ? WHERE day = ?",
                  (start, end, working, day))
    conn.commit()

def add_exception(from_date, to_date):
    cursor.execute("INSERT INTO exceptions (date_from, date_to, reason) VALUES (?, ?, 'Отпуск')", (from_date, to_date))
    conn.commit()

def get_schedule_text():
    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    sched = cursor.execute("SELECT day, start_time, end_time, is_working FROM schedule ORDER BY day").fetchall()
    
    text = "📅 Расписание:\n\n"
    for s in sched:
        if s[3]:
            text += f"{days[s[0]]}: {s[1]} - {s[2]}\n"
        else:
            text += f"{days[s[0]]}: Выходной\n"
    
    ex = cursor.execute("SELECT date_from, date_to FROM exceptions").fetchall()
    if ex:
        text += "\n🚫 Отпуск:\n"
        for e in ex:
            text += f"• {e[0]} - {e[1]}\n"
    
    return text

def get_client_bonuses(tg_id):
    client = cursor.execute("SELECT id, visits, spent FROM clients WHERE tg_id = ?", (tg_id,)).fetchone()
    if client:
        return client[1], client[2]
    return 0, 0

def update_client_stats(client_id, spent_amount):
    cursor.execute("UPDATE clients SET visits = visits + 1, spent = spent + ? WHERE id = ?", (spent_amount, client_id))
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
                SELECT a.id, a.time, c.tg_id, c.name, s.name
                FROM appointments a
                JOIN clients c ON a.client_id = c.id
                JOIN services s ON a.service_id = s.id
                WHERE a.date = ? AND a.status = 'active' AND a.reminder_24h = 0
            ''', (tomorrow,)).fetchall()
            
            for app in apps_24h:
                try:
                    await bot.send_message(
                        app[2],
                        f"🔔 НАПОМИНАНИЕ ЗА 24 ЧАСА\n\n"
                        f"Завтра в {app[1]} у вас запись на {app[4]}"
                    )
                    cursor.execute("UPDATE appointments SET reminder_24h = 1 WHERE id = ?", (app[0],))
                    conn.commit()
                except:
                    pass
            
            # Напоминания за 2 часа
            apps_2h = cursor.execute('''
                SELECT a.id, a.time, c.tg_id, c.name, s.name
                FROM appointments a
                JOIN clients c ON a.client_id = c.id
                JOIN services s ON a.service_id = s.id
                WHERE a.date = ? AND a.status = 'active' AND a.reminder_2h = 0
            ''', (today,)).fetchall()
            
            for app in apps_2h:
                try:
                    app_time = datetime.strptime(app[1], "%H:%M")
                    if (now.hour + 2) >= app_time.hour:
                        await bot.send_message(
                            app[2],
                            f"🔔 НАПОМИНАНИЕ ЗА 2 ЧАСА\n\n"
                            f"Сегодня в {app[1]} у вас запись на {app[4]}"
                        )
                        cursor.execute("UPDATE appointments SET reminder_2h = 1 WHERE id = ?", (app[0],))
                        conn.commit()
                except:
                    pass
                    
            await asyncio.sleep(1800)  # 30 минут
        except Exception as e:
            print(f"Ошибка в напоминаниях: {e}")
            await asyncio.sleep(60)

# ========== КЛАВИАТУРЫ ==========

def main_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📅 Записаться", "💰 Цены")
    kb.row("📍 Контакты", "📋 Мои записи")
    kb.row("🎁 Мои бонусы")
    return kb

def services_keyboard():
    kb = InlineKeyboardMarkup(row_width=1)
    for s in cursor.execute("SELECT id, name, price FROM services").fetchall():
        kb.add(InlineKeyboardButton(f"{s[1]} - {s[2]}₽", callback_data=f"srv_{s[0]}"))
    return kb

def dates_keyboard():
    kb = InlineKeyboardMarkup(row_width=3)
    today = datetime.now()
    for i in range(14):
        date = today + timedelta(days=i)
        date_str = date.strftime("%d.%m.%Y")
        slots = get_free_slots(date_str)
        text = date.strftime("%d %b")
        if not slots:
            text = "❌ " + text
        kb.add(InlineKeyboardButton(text, callback_data=f"dat_{date_str}"))
    return kb

def time_keyboard(slots):
    kb = InlineKeyboardMarkup(row_width=3)
    for s in slots[:12]:
        kb.add(InlineKeyboardButton(s, callback_data=f"tim_{s}"))
    return kb

def confirm_keyboard():
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("✅ Да", callback_data="conf_yes"),
        InlineKeyboardButton("❌ Нет", callback_data="conf_no")
    )
    return kb

def admin_keyboard():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.row(
        InlineKeyboardButton("📊 Статистика", callback_data="adm_stats"),
        InlineKeyboardButton("📅 Сегодня", callback_data="adm_today")
    )
    kb.row(
        InlineKeyboardButton("📋 Расписание", callback_data="adm_sched"),
        InlineKeyboardButton("✏️ Изменить день", callback_data="adm_edit")
    )
    kb.row(
        InlineKeyboardButton("🚫 Отпуск", callback_data="adm_vac"),
        InlineKeyboardButton("✅ Убрать отпуск", callback_data="adm_rem")
    )
    return kb

def days_keyboard():
    kb = InlineKeyboardMarkup(row_width=4)
    days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    for i, d in enumerate(days):
        kb.insert(InlineKeyboardButton(d, callback_data=f"day_{i}"))
    kb.row(InlineKeyboardButton("🔙 Назад", callback_data="adm_back"))
    return kb

# ========== ОБРАБОТЧИКИ ==========

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    cursor.execute("INSERT OR IGNORE INTO clients (tg_id, name) VALUES (?, ?)",
                  (message.from_user.id, message.from_user.first_name))
    conn.commit()
    
    await message.answer(
        "👋 Добро пожаловать!\n\n"
        "✨ Функции:\n"
        "• Запись онлайн\n"
        "• Напоминания о записи\n"
        "• Бонусная программа\n"
        "• Просмотр своих записей",
        reply_markup=main_keyboard()
    )

@dp.message_handler(lambda m: m.text == "💰 Цены")
async def prices(message: types.Message):
    text = "💅 Наши услуги:\n\n"
    for s in cursor.execute("SELECT name, price FROM services").fetchall():
        text += f"• {s[0]}: {s[1]}₽\n"
    await message.answer(text)

@dp.message_handler(lambda m: m.text == "📍 Контакты")
async def contacts(message: types.Message):
    await message.answer(
        "📍 Адрес: ул. Ленина, 15\n"
        "📞 Телефон: +7 (999) 123-45-67\n\n" +
        get_schedule_text()
    )

@dp.message_handler(lambda m: m.text == "📋 Мои записи")
async def my_apps(message: types.Message):
    apps = cursor.execute('''
        SELECT a.date, a.time, s.name, a.price, a.id
        FROM appointments a
        JOIN clients c ON a.client_id = c.id
        JOIN services s ON a.service_id = s.id
        WHERE c.tg_id = ? AND a.status = 'active'
        ORDER BY a.date
    ''', (message.from_user.id,)).fetchall()
    
    if not apps:
        await message.answer("У вас нет активных записей")
        return
    
    kb = InlineKeyboardMarkup()
    for a in apps:
        kb.add(InlineKeyboardButton(
            f"{a[0]} {a[1]} - {a[2]}",
            callback_data=f"app_{a[4]}"
        ))
    
    await message.answer("Ваши записи:", reply_markup=kb)

@dp.message_handler(lambda m: m.text == "🎁 Мои бонусы")
async def bonuses(message: types.Message):
    visits, spent = get_client_bonuses(message.from_user.id)
    next_discount = 10 - (visits % 10)
    
    text = (
        "🎁 БОНУСНАЯ ПРОГРАММА\n\n"
        f"✅ Посещений: {visits}\n"
        f"💰 Потрачено: {spent}₽\n"
        f"💎 Скидка: {(visits // 10) * 5}%\n"
        f"🔜 До следующей скидки: {next_discount} посещений"
    )
    await message.answer(text)

@dp.message_handler(lambda m: m.text == "📅 Записаться")
async def book_start(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer("Выберите услугу:", reply_markup=services_keyboard())
    await BookingStates.service.set()

# ========== ПРОЦЕСС ЗАПИСИ ==========

@dp.callback_query_handler(lambda c: c.data.startswith('srv_'), state=BookingStates.service)
async def book_service(call: types.CallbackQuery, state: FSMContext):
    service_id = int(call.data.split('_')[1])
    await state.update_data(service_id=service_id)
    
    service = cursor.execute("SELECT name, price FROM services WHERE id = ?", (service_id,)).fetchone()
    await state.update_data(service_name=service[0], service_price=service[1])
    
    await call.message.edit_text("Выберите дату:", reply_markup=dates_keyboard())
    await BookingStates.date.set()
    await call.answer()

@dp.callback_query_handler(lambda c: c.data.startswith('dat_'), state=BookingStates.date)
async def book_date(call: types.CallbackQuery, state: FSMContext):
    date = call.data.split('_')[1]
    slots = get_free_slots(date)
    
    if not slots:
        await call.message.edit_text("Нет свободных слотов. Выберите другую дату:", 
                                    reply_markup=dates_keyboard())
        await call.answer()
        return
    
    await state.update_data(date=date)
    await call.message.edit_text("Выберите время:", reply_markup=time_keyboard(slots))
    await BookingStates.time.set()
    await call.answer()

@dp.callback_query_handler(lambda c: c.data.startswith('tim_'), state=BookingStates.time)
async def book_time(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(time=call.data.split('_')[1])
    await call.message.edit_text("Введите ваше имя:")
    await BookingStates.name.set()
    await call.answer()

@dp.message_handler(state=BookingStates.name)
async def book_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введите номер телефона:")
    await BookingStates.phone.set()

@dp.message_handler(state=BookingStates.phone)
async def book_phone(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.text)
    data = await state.get_data()
    
    await message.answer(
        f"📝 Проверьте данные:\n\n"
        f"Услуга: {data['service_name']}\n"
        f"Дата: {data['date']}\n"
        f"Время: {data['time']}\n"
        f"Имя: {data['name']}\n"
        f"Телефон: {data['phone']}\n"
        f"Сумма: {data['service_price']}₽\n\n"
        f"✅ После подтверждения придёт напоминание",
        reply_markup=confirm_keyboard()
    )
    await BookingStates.confirm.set()

@dp.callback_query_handler(lambda c: c.data == "conf_yes", state=BookingStates.confirm)
async def book_confirm(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    
    client = cursor.execute("SELECT id FROM clients WHERE tg_id = ?", (call.from_user.id,)).fetchone()
    
    if not client:
        cursor.execute("INSERT INTO clients (tg_id, name, phone) VALUES (?, ?, ?)",
                      (call.from_user.id, data['name'], data['phone']))
        client_id = cursor.lastrowid
    else:
        client_id = client[0]
    
    cursor.execute('''
        INSERT INTO appointments (client_id, service_id, date, time, price)
        VALUES (?, ?, ?, ?, ?)
    ''', (client_id, data['service_id'], data['date'], data['time'], data['service_price']))
    conn.commit()
    
    update_client_stats(client_id, data['service_price'])
    
    await call.message.edit_text(
        "✅ ЗАПИСЬ ПОДТВЕРЖДЕНА!\n\n"
        f"📍 {data['date']} в {data['time']}\n"
        f"💅 {data['service_name']}\n"
        f"💵 {data['service_price']}₽\n\n"
        "🔔 Напоминания придут за 24 и 2 часа"
    )
    
    # Уведомление админам
    for admin_id in ADMINS:
        try:
            await bot.send_message(
                admin_id,
                f"🔔 НОВАЯ ЗАПИСЬ!\n\n"
                f"Клиент: {data['name']}\n"
                f"Тел: {data['phone']}\n"
                f"Услуга: {data['service_name']}\n"
                f"Дата: {data['date']} {data['time']}"
            )
        except:
            pass
    
    await state.finish()
    await call.answer()

@dp.callback_query_handler(lambda c: c.data == "conf_no", state=BookingStates.confirm)
async def book_cancel(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text("Запись отменена")
    await state.finish()
    await call.answer()

# ========== ОТМЕНА ЗАПИСИ ==========

@dp.callback_query_handler(lambda c: c.data.startswith('app_'))
async def cancel_app(call: types.CallbackQuery):
    app_id = int(call.data.split('_')[1])
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Подтвердить отмену", callback_data=f"del_{app_id}"))
    kb.add(InlineKeyboardButton("🔙 Назад", callback_data="back_to_apps"))
    
    await call.message.edit_text("Отменить запись?", reply_markup=kb)
    await call.answer()

@dp.callback_query_handler(lambda c: c.data.startswith('del_'))
async def confirm_cancel(call: types.CallbackQuery):
    app_id = int(call.data.split('_')[1])
    
    app_info = cursor.execute('''
        SELECT c.name, c.phone, a.date, a.time
        FROM appointments a
        JOIN clients c ON a.client_id = c.id
        WHERE a.id = ?
    ''', (app_id,)).fetchone()
    
    cursor.execute("UPDATE appointments SET status = 'cancelled' WHERE id = ?", (app_id,))
    conn.commit()
    
    await call.message.edit_text("✅ Запись отменена")
    
    for admin_id in ADMINS:
        try:
            await bot.send_message(
                admin_id,
                f"❌ ОТМЕНА ЗАПИСИ\n\n"
                f"Клиент: {app_info[0]}\n"
                f"Тел: {app_info[1]}\n"
                f"Дата: {app_info[2]} {app_info[3]}"
            )
        except:
            pass
    
    await call.answer()

@dp.callback_query_handler(lambda c: c.data == "back_to_apps")
async def back_to_apps(call: types.CallbackQuery):
    apps = cursor.execute('''
        SELECT a.date, a.time, s.name, a.price, a.id
        FROM appointments a
        JOIN clients c ON a.client_id = c.id
        JOIN services s ON a.service_id = s.id
        WHERE c.tg_id = ? AND a.status = 'active'
        ORDER BY a.date
    ''', (call.from_user.id,)).fetchall()
    
    kb = InlineKeyboardMarkup()
    for a in apps:
        kb.add(InlineKeyboardButton(f"{a[0]} {a[1]} - {a[2]}", callback_data=f"app_{a[4]}"))
    
    await call.message.edit_text("Ваши записи:", reply_markup=kb)
    await call.answer()

# ========== АДМИНКА ==========

@dp.message_handler(commands=['admin'])
async def admin_menu(message: types.Message):
    if message.from_user.id not in ADMINS:
        await message.answer("⛔ Доступ запрещен")
        return
    
    await message.answer("🔧 ПАНЕЛЬ АДМИНИСТРАТОРА", reply_markup=admin_keyboard())

@dp.callback_query_handler(lambda c: c.data == "adm_stats")
async def admin_stats(call: types.CallbackQuery):
    today = datetime.now().strftime("%d.%m.%Y")
    month_start = datetime.now().replace(day=1).strftime("%d.%m.%Y")
    
    t_count = cursor.execute("SELECT COUNT(*) FROM appointments WHERE date = ? AND status = 'active'", (today,)).fetchone()[0]
    t_sum = cursor.execute("SELECT SUM(price) FROM appointments WHERE date = ? AND status = 'active'", (today,)).fetchone()[0] or 0
    
    m_count = cursor.execute("SELECT COUNT(*) FROM appointments WHERE date >= ? AND status = 'active'", (month_start,)).fetchone()[0]
    m_sum = cursor.execute("SELECT SUM(price) FROM appointments WHERE date >= ? AND status = 'active'", (month_start,)).fetchone()[0] or 0
    
    total_clients = cursor.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
    
    text = (
        f"📊 СТАТИСТИКА\n\n"
        f"📅 Сегодня:\n"
        f"   Записей: {t_count}\n"
        f"   Выручка: {t_sum}₽\n\n"
        f"📆 За месяц:\n"
        f"   Записей: {m_count}\n"
        f"   Выручка: {m_sum}₽\n\n"
        f"👥 Всего клиентов: {total_clients}"
    )
    
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup().add(
        InlineKeyboardButton("🔙 Назад", callback_data="adm_back")
    ))
    await call.answer()

@dp.callback_query_handler(lambda c: c.data == "adm_today")
async def admin_today(call: types.CallbackQuery):
    today = datetime.now().strftime("%d.%m.%Y")
    apps = cursor.execute('''
        SELECT a.time, c.name, c.phone, s.name
        FROM appointments a
        JOIN clients c ON a.client_id = c.id
        JOIN services s ON a.service_id = s.id
        WHERE a.date = ? AND a.status = 'active'
        ORDER BY a.time
    ''', (today,)).fetchall()
    
    if not apps:
        text = "На сегодня записей нет"
    else:
        text = "📅 ЗАПИСИ НА СЕГОДНЯ\n\n"
        for a in apps:
            text += f"⏰ {a[0]} - {a[1]}\n📞 {a[2]}\n💅 {a[3]}\n\n"
    
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup().add(
        InlineKeyboardButton("🔙 Назад", callback_data="adm_back")
    ))
    await call.answer()

@dp.callback_query_handler(lambda c: c.data == "adm_sched")
async def admin_schedule(call: types.CallbackQuery):
    await call.message.edit_text(
        get_schedule_text(),
        reply_markup=InlineKeyboardMarkup().add(
            InlineKeyboardButton("🔙 Назад", callback_data="adm_back")
        )
    )
    await call.answer()

@dp.callback_query_handler(lambda c: c.data == "adm_edit")
async def admin_edit(call: types.CallbackQuery):
    await call.message.edit_text("Выберите день:", reply_markup=days_keyboard())
    await call.answer()

@dp.callback_query_handler(lambda c: c.data.startswith('day_'))
async def edit_day(call: types.CallbackQuery, state: FSMContext):
    day = int(call.data.split('_')[1])
    await state.update_data(edit_day=day)
    
    sched = cursor.execute("SELECT start_time, end_time, is_working FROM schedule WHERE day = ?", (day,)).fetchone()
    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    
    if sched[2]:
        text = f"{days[day]}\nТекущее: {sched[0]} - {sched[1]}\n\nВведите новое время (10:00-18:00) или 'выходной'"
    else:
        text = f"{days[day]}\nТекущее: Выходной\n\nВведите время (10:00-18:00) или 'выходной'"
    
    await call.message.edit_text(text)
    await ScheduleStates.edit_day.set()
    await call.answer()

@dp.message_handler(state=ScheduleStates.edit_day)
async def save_schedule(message: types.Message, state: FSMContext):
    data = await state.get_data()
    day = data['edit_day']
    text = message.text.lower().strip()
    
    if text == 'выходной':
        update_schedule(day, "00:00", "00:00", 0)
        await message.answer("✅ День установлен как выходной")
    else:
        try:
            times = text.split('-')
            start = times[0].strip()
            end = times[1].strip()
            if len(start) == 5 and len(end) == 5:
                update_schedule(day, start, end, 1)
                await message.answer(f"✅ Установлено: {start} - {end}")
            else:
                await message.answer("❌ Неверный формат")
        except:
            await message.answer("❌ Ошибка формата")
    
    await state.finish()
    await message.answer("Что дальше?", reply_markup=admin_keyboard())

@dp.callback_query_handler(lambda c: c.data == "adm_vac")
async def admin_vacation(call: types.CallbackQuery):
    await call.message.edit_text(
        "Введите даты отпуска (ДД.ММ.ГГГГ-ДД.ММ.ГГГГ):\n"
        "Пример: 01.06.2024-10.06.2024"
    )
    await ScheduleStates.vacation.set()
    await call.answer()

@dp.message_handler(state=ScheduleStates.vacation)
async def save_vacation(message: types.Message, state: FSMContext):
    try:
        dates = message.text.split('-')
        date_from = dates[0].strip()
        date_to = dates[1].strip()
        
        datetime.strptime(date_from, "%d.%m.%Y")
        datetime.strptime(date_to, "%d.%m.%Y")
        
        add_exception(date_from, date_to)
        await message.answer(f"✅ Отпуск добавлен с {date_from} по {date_to}")
    except:
        await message.answer("❌ Ошибка формата")
    
    await state.finish()
    await message.answer("Что дальше?", reply_markup=admin_keyboard())

@dp.callback_query_handler(lambda c: c.data == "adm_rem")
async def admin_remove(call: types.CallbackQuery):
    ex = cursor.execute("SELECT date_from, date_to FROM exceptions").fetchall()
    
    if not ex:
        await call.message.edit_text(
            "Нет активных исключений",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("🔙 Назад", callback_data="adm_back")
            )
        )
        await call.answer()
        return
    
    kb = InlineKeyboardMarkup()
    for e in ex:
        kb.add(InlineKeyboardButton(f"{e[0]} - {e[1]}", callback_data=f"rem_{e[0]}"))
    kb.add(InlineKeyboardButton("🔙 Назад", callback_data="adm_back"))
    
    await call.message.edit_text("Выберите период:", reply_markup=kb)
    await call.answer()

@dp.callback_query_handler(lambda c: c.data.startswith('rem_'))
async def remove_exception(call: types.CallbackQuery):
    date_from = call.data.split('_')[1]
    cursor.execute("DELETE FROM exceptions WHERE date_from = ?", (date_from,))
    conn.commit()
    
    await call.message.edit_text("✅ Исключение удалено")
    await call.answer()

@dp.callback_query_handler(lambda c: c.data == "adm_back")
async def admin_back(call: types.CallbackQuery):
    await call.message.edit_text("🔧 ПАНЕЛЬ АДМИНИСТРАТОРА", reply_markup=admin_keyboard())
    await call.answer()

# Команда отмены
@dp.message_handler(commands=['cancel'], state='*')
async def cancel_cmd(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer("Действие отменено", reply_markup=main_keyboard())

# ========== ЗАПУСК ==========

async def on_startup(dp):
    asyncio.create_task(reminder_check())
    print("✅ Планировщик напоминаний запущен")

if __name__ == '__main__':
    print("🚀 БОТ ЗАПУСКАЕТСЯ...")
    print(f"👑 Администраторы: {ADMINS}")
    print(f"📁 База данных: {DB_PATH}")
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)