import logging
import sqlite3
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage

# Загружаем переменные
load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')

# Получаем список админов (можно через запятую или пробел)
admin_ids_str = os.getenv('ADMIN_ID', '0')
ADMINS = []
for part in admin_ids_str.replace(',', ' ').split():
    try:
        ADMINS.append(int(part.strip()))
    except:
        pass
if not ADMINS:
    ADMINS = [0]

# Проверка токена
if not BOT_TOKEN:
    print("❌ ОШИБКА: Токен не найден в файле .env!")
    print("Создай файл .env в папке с ботом и напиши в нем:")
    print('BOT_TOKEN=8344454276:AAEtymshVLP424Xx7nvn3h6GJ1Nx1ciQeg4')
    print('ADMIN_ID=твой_телеграм_id,второй_id')
    exit()

print(f"✅ Токен загружен успешно!")
print(f"✅ Администраторы: {ADMINS}")

# Настройки
WORK_START = 10
WORK_END = 20
LUNCH_START = 13
LUNCH_END = 14

# Логирование
logging.basicConfig(level=logging.INFO)

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

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
conn = sqlite3.connect('nail_studio.db', check_same_thread=False)
cursor = conn.cursor()

# Удаляем старые таблицы если они есть и создаем заново
cursor.execute("DROP TABLE IF EXISTS schedule")
cursor.execute("DROP TABLE IF EXISTS services")
cursor.execute("DROP TABLE IF EXISTS clients")
cursor.execute("DROP TABLE IF EXISTS appointments")
cursor.execute("DROP TABLE IF EXISTS exceptions")

# Создание таблиц заново
cursor.execute('''CREATE TABLE services (
    id INTEGER PRIMARY KEY AUTOINCREMENT, 
    name TEXT, 
    price INTEGER, 
    duration INTEGER)''')

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
    service_id INTEGER,
    date TEXT, 
    time TEXT, 
    price INTEGER, 
    status TEXT DEFAULT 'active')''')

cursor.execute('''CREATE TABLE schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day INTEGER, 
    start_time TEXT, 
    end_time TEXT, 
    is_working INTEGER DEFAULT 1)''')

cursor.execute('''CREATE TABLE exceptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, 
    date_from TEXT, 
    date_to TEXT, 
    reason TEXT)''')
conn.commit()

# Добавляем расписание
for day in range(7):
    if day < 5:  # Пн-Пт
        cursor.execute("INSERT INTO schedule (day, start_time, end_time, is_working) VALUES (?, '10:00', '20:00', 1)", (day,))
    elif day == 5:  # Сб
        cursor.execute("INSERT INTO schedule (day, start_time, end_time, is_working) VALUES (?, '10:00', '18:00', 1)", (day,))
    else:  # Вс
        cursor.execute("INSERT INTO schedule (day, start_time, end_time, is_working) VALUES (?, '00:00', '00:00', 0)", (day,))
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

print("✅ База данных создана заново")

# ========== ФУНКЦИИ ==========

def get_working_hours(date_str):
    """Получить рабочие часы на дату"""
    # Проверка исключений
    if cursor.execute("SELECT * FROM exceptions WHERE date_from <= ? AND date_to >= ?", 
                     (date_str, date_str)).fetchone():
        return []
    
    date = datetime.strptime(date_str, "%d.%m.%Y")
    day = date.weekday()
    
    # Получаем расписание
    sched = cursor.execute("SELECT start_time, end_time, is_working FROM schedule WHERE day = ?", (day,)).fetchone()
    if not sched or not sched[2]:
        return []
    
    # Генерируем слоты
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
    """Получить свободные слоты"""
    working = get_working_hours(date)
    if not working:
        return []
    
    busy = cursor.execute(
        "SELECT time FROM appointments WHERE date = ? AND status = 'active'", 
        (date,)
    ).fetchall()
    busy = [b[0] for b in busy]
    
    return [s for s in working if s not in busy]

def update_schedule(day, start, end, working):
    cursor.execute("UPDATE schedule SET start_time = ?, end_time = ?, is_working = ? WHERE day = ?",
                  (start, end, working, day))
    conn.commit()

def add_exception(from_date, to_date):
    cursor.execute("INSERT INTO exceptions (date_from, date_to, reason) VALUES (?, ?, 'Отпуск')",
                  (from_date, to_date))
    conn.commit()

def get_schedule_text():
    """Получить текст расписания"""
    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    sched = cursor.execute("SELECT day, start_time, end_time, is_working FROM schedule ORDER BY day").fetchall()
    
    text = "📅 Текущее расписание:\n\n"
    for s in sched:
        day_num, start, end, working = s
        if working:
            text += f"{days[day_num]}: {start} - {end}\n"
        else:
            text += f"{days[day_num]}: Выходной\n"
    
    # Исключения
    ex = cursor.execute("SELECT date_from, date_to FROM exceptions").fetchall()
    if ex:
        text += "\n🚫 Исключения (отпуск):\n"
        for e in ex:
            text += f"• {e[0]} - {e[1]}\n"
    
    return text

# ========== КЛАВИАТУРЫ ==========

def main_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📅 Записаться", "💰 Цены")
    kb.row("📍 Контакты", "📋 Мои записи")
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
    days_short = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    for i, d in enumerate(days_short):
        kb.insert(InlineKeyboardButton(d, callback_data=f"day_{i}"))
    kb.row(InlineKeyboardButton("🔙 Назад", callback_data="adm_back"))
    return kb

# ========== ОБРАБОТЧИКИ ==========

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.answer(
        "👋 Добро пожаловать в студию маникюра!\n\nВыберите действие:",
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
        await message.answer("У вас нет записей")
        return
    
    kb = InlineKeyboardMarkup()
    for a in apps:
        kb.add(InlineKeyboardButton(
            f"{a[0]} {a[1]} - {a[2]}",
            callback_data=f"app_{a[4]}"
        ))
    
    await message.answer("Ваши записи:", reply_markup=kb)

@dp.message_handler(lambda m: m.text == "📅 Записаться")
async def book_start(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer("Выберите услугу:", reply_markup=services_keyboard())
    await BookingStates.service.set()

# Процесс записи
@dp.callback_query_handler(lambda c: c.data.startswith('srv_'), state=BookingStates.service)
async def book_service(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(service=int(call.data.split('_')[1]))
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
    
    service = cursor.execute("SELECT name, price FROM services WHERE id = ?", 
                            (data['service'],)).fetchone()
    
    await message.answer(
        f"📝 Проверьте данные:\n\n"
        f"Услуга: {service[0]}\n"
        f"Цена: {service[1]}₽\n"
        f"Дата: {data['date']}\n"
        f"Время: {data['time']}\n"
        f"Имя: {data['name']}\n"
        f"Телефон: {data['phone']}\n\n"
        f"Всё верно?",
        reply_markup=confirm_keyboard()
    )
    await BookingStates.confirm.set()

@dp.callback_query_handler(lambda c: c.data == "conf_yes", state=BookingStates.confirm)
async def book_confirm(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    
    # Создаем клиента
    cursor.execute(
        "INSERT OR IGNORE INTO clients (tg_id, name, phone) VALUES (?, ?, ?)",
        (call.from_user.id, data['name'], data['phone'])
    )
    client = cursor.execute("SELECT id FROM clients WHERE tg_id = ?", 
                           (call.from_user.id,)).fetchone()
    
    # Создаем запись
    service = cursor.execute("SELECT price FROM services WHERE id = ?", 
                            (data['service'],)).fetchone()
    
    cursor.execute('''
        INSERT INTO appointments (client_id, service_id, date, time, price)
        VALUES (?, ?, ?, ?, ?)
    ''', (client[0], data['service'], data['date'], data['time'], service[0]))
    conn.commit()
    
    await call.message.edit_text("✅ Запись подтверждена!")
    
    # Уведомление ВСЕМ админам (ИЗМЕНЕНО)
    if ADMINS:
        for admin_id in ADMINS:
            try:
                await bot.send_message(
                    admin_id,
                    f"🔔 Новая запись!\n"
                    f"Клиент: {data['name']}\n"
                    f"Тел: {data['phone']}\n"
                    f"Дата: {data['date']} {data['time']}"
                )
            except:
                pass  # Игнорируем ошибки
    
    await state.finish()
    await call.answer()

@dp.callback_query_handler(lambda c: c.data == "conf_no", state=BookingStates.confirm)
async def book_cancel(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text("Запись отменена")
    await state.finish()
    await call.answer()

# Отмена записи
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
    cursor.execute("UPDATE appointments SET status = 'cancelled' WHERE id = ?", (app_id,))
    conn.commit()
    
    await call.message.edit_text("✅ Запись отменена")
    
    # Уведомление ВСЕМ админам об отмене (ИЗМЕНЕНО)
    if ADMINS:
        for admin_id in ADMINS:
            try:
                await bot.send_message(admin_id, f"❌ Клиент отменил запись #{app_id}")
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
    if message.from_user.id not in ADMINS:  # ИЗМЕНЕНО - проверка по списку
        await message.answer("⛔ Доступ запрещен")
        return
    
    await message.answer("🔧 Панель администратора:", reply_markup=admin_keyboard())

@dp.callback_query_handler(lambda c: c.data == "adm_stats")
async def admin_stats(call: types.CallbackQuery):
    if call.from_user.id not in ADMINS:  # ИЗМЕНЕНО
        await call.answer("⛔ Доступ запрещен")
        return
    
    today = datetime.now().strftime("%d.%m.%Y")
    t_count = cursor.execute(
        "SELECT COUNT(*) FROM appointments WHERE date = ? AND status = 'active'", 
        (today,)
    ).fetchone()[0]
    t_sum = cursor.execute(
        "SELECT SUM(price) FROM appointments WHERE date = ? AND status = 'active'", 
        (today,)
    ).fetchone()[0] or 0
    
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%d.%m.%Y")
    w_count = cursor.execute(
        "SELECT COUNT(*) FROM appointments WHERE date >= ? AND status = 'active'", 
        (week_ago,)
    ).fetchone()[0]
    w_sum = cursor.execute(
        "SELECT SUM(price) FROM appointments WHERE date >= ? AND status = 'active'", 
        (week_ago,)
    ).fetchone()[0] or 0
    
    await call.message.edit_text(
        f"📊 Статистика:\n\n"
        f"Сегодня: {t_count} записей, {t_sum}₽\n"
        f"Неделя: {w_count} записей, {w_sum}₽",
        reply_markup=InlineKeyboardMarkup().add(
            InlineKeyboardButton("🔙 Назад", callback_data="adm_back")
        )
    )
    await call.answer()

@dp.callback_query_handler(lambda c: c.data == "adm_today")
async def admin_today(call: types.CallbackQuery):
    if call.from_user.id not in ADMINS:  # ИЗМЕНЕНО
        await call.answer("⛔ Доступ запрещен")
        return
    
    today = datetime.now().strftime("%d.%m.%Y")
    apps = cursor.execute('''
        SELECT a.time, c.name, s.name, c.phone
        FROM appointments a
        JOIN clients c ON a.client_id = c.id
        JOIN services s ON a.service_id = s.id
        WHERE a.date = ? AND a.status = 'active'
        ORDER BY a.time
    ''', (today,)).fetchall()
    
    if not apps:
        text = "На сегодня записей нет"
    else:
        text = "📅 Записи на сегодня:\n\n"
        for a in apps:
            text += f"{a[0]} - {a[1]} ({a[2]})\n📞 {a[3]}\n\n"
    
    await call.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup().add(
            InlineKeyboardButton("🔙 Назад", callback_data="adm_back")
        )
    )
    await call.answer()

@dp.callback_query_handler(lambda c: c.data == "adm_sched")
async def admin_schedule(call: types.CallbackQuery):
    if call.from_user.id not in ADMINS:  # ИЗМЕНЕНО
        await call.answer("⛔ Доступ запрещен")
        return
    
    await call.message.edit_text(
        get_schedule_text(),
        reply_markup=InlineKeyboardMarkup().add(
            InlineKeyboardButton("🔙 Назад", callback_data="adm_back")
        )
    )
    await call.answer()

@dp.callback_query_handler(lambda c: c.data == "adm_edit")
async def admin_edit(call: types.CallbackQuery):
    if call.from_user.id not in ADMINS:  # ИЗМЕНЕНО
        await call.answer("⛔ Доступ запрещен")
        return
    
    await call.message.edit_text(
        "Выберите день для изменения:",
        reply_markup=days_keyboard()
    )
    await call.answer()

@dp.callback_query_handler(lambda c: c.data.startswith('day_'))
async def edit_day(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id not in ADMINS:  # ИЗМЕНЕНО
        await call.answer("⛔ Доступ запрещен")
        return
    
    day = int(call.data.split('_')[1])
    await state.update_data(edit_day=day)
    
    sched = cursor.execute("SELECT start_time, end_time, is_working FROM schedule WHERE day = ?", (day,)).fetchone()
    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    
    if sched[2]:
        text = f"{days[day]}\nТекущее: {sched[0]} - {sched[1]}\n\nВведите новое время (например 10:00-18:00) или 'выходной'"
    else:
        text = f"{days[day]}\nТекущее: Выходной\n\nВведите время (например 10:00-18:00) или 'выходной'"
    
    await call.message.edit_text(text)
    await ScheduleStates.edit_day.set()
    await call.answer()

@dp.message_handler(state=ScheduleStates.edit_day)
async def save_schedule(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:  # ИЗМЕНЕНО
        await message.answer("⛔ Доступ запрещен")
        await state.finish()
        return
    
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
            # Проверка формата
            if len(start) == 5 and len(end) == 5 and ':' in start and ':' in end:
                update_schedule(day, start, end, 1)
                await message.answer(f"✅ Установлено: {start} - {end}")
            else:
                await message.answer("❌ Неверный формат. Используйте: 10:00-18:00")
        except:
            await message.answer("❌ Ошибка формата. Используйте: 10:00-18:00")
    
    await state.finish()
    await message.answer("Что дальше?", reply_markup=admin_keyboard())

@dp.callback_query_handler(lambda c: c.data == "adm_vac")
async def admin_vacation(call: types.CallbackQuery):
    if call.from_user.id not in ADMINS:  # ИЗМЕНЕНО
        await call.answer("⛔ Доступ запрещен")
        return
    
    await call.message.edit_text(
        "Введите даты отпуска (ДД.ММ.ГГГГ-ДД.ММ.ГГГГ):\n"
        "Пример: 01.06.2024-10.06.2024"
    )
    await ScheduleStates.vacation.set()
    await call.answer()

@dp.message_handler(state=ScheduleStates.vacation)
async def save_vacation(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:  # ИЗМЕНЕНО
        await message.answer("⛔ Доступ запрещен")
        await state.finish()
        return
    
    try:
        dates = message.text.split('-')
        date_from = dates[0].strip()
        date_to = dates[1].strip()
        
        # Проверка формата
        datetime.strptime(date_from, "%d.%m.%Y")
        datetime.strptime(date_to, "%d.%m.%Y")
        
        add_exception(date_from, date_to)
        await message.answer(f"✅ Отпуск добавлен с {date_from} по {date_to}")
    except:
        await message.answer("❌ Ошибка формата. Используйте: ДД.ММ.ГГГГ-ДД.ММ.ГГГГ")
    
    await state.finish()
    await message.answer("Что дальше?", reply_markup=admin_keyboard())

@dp.callback_query_handler(lambda c: c.data == "adm_rem")
async def admin_remove(call: types.CallbackQuery):
    if call.from_user.id not in ADMINS:  # ИЗМЕНЕНО
        await call.answer("⛔ Доступ запрещен")
        return
    
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
        kb.add(InlineKeyboardButton(
            f"{e[0]} - {e[1]}",
            callback_data=f"rem_{e[0]}"
        ))
    kb.add(InlineKeyboardButton("🔙 Назад", callback_data="adm_back"))
    
    await call.message.edit_text("Выберите период для удаления:", reply_markup=kb)
    await call.answer()

@dp.callback_query_handler(lambda c: c.data.startswith('rem_'))
async def remove_exception(call: types.CallbackQuery):
    if call.from_user.id not in ADMINS:  # ИЗМЕНЕНО
        await call.answer("⛔ Доступ запрещен")
        return
    
    date_from = call.data.split('_')[1]
    cursor.execute("DELETE FROM exceptions WHERE date_from = ?", (date_from,))
    conn.commit()
    
    await call.message.edit_text("✅ Исключение удалено")
    await call.answer()

@dp.callback_query_handler(lambda c: c.data == "adm_back")
async def admin_back(call: types.CallbackQuery):
    if call.from_user.id not in ADMINS:  # ИЗМЕНЕНО
        await call.answer("⛔ Доступ запрещен")
        return
    
    await call.message.edit_text(
        "🔧 Панель администратора:",
        reply_markup=admin_keyboard()
    )
    await call.answer()

# Команда отмены
@dp.message_handler(commands=['cancel'], state='*')
async def cancel_cmd(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer("Действие отменено", reply_markup=main_keyboard())

# ========== ЗАПУСК ==========

if __name__ == '__main__':
    print("🚀 Бот с расписанием запущен!")
    print(f"👤 Администраторы: {ADMINS}")
    print("📅 Команда /admin - панель управления")
    executor.start_polling(dp, skip_updates=True)