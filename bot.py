import asyncio
import sqlite3
import os
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from apscheduler.schedulers.asyncio import AsyncIOScheduler

TOKEN = "YOUR_BOT_TOKEN"
ADMIN_ID = 123456789  # Замени на свой Telegram ID
MATERIAL_TEXT = "📚 Ваш ежедневный материал: [полезный контент]"
POLL_QUESTION = "Как вам сегодняшний материал?"
POLL_OPTIONS = ["Отлично!", "Хорошо", "Средне", "Не понравилось"]

bot = Bot(token=TOKEN)
dp = Dispatcher(bot)
scheduler = AsyncIOScheduler()

db_path = "bot_database.db"

# Создание базы данных, если ее нет
if not os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        'CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)')
    cursor.execute(
        'CREATE TABLE stats (date TEXT, materials_sent INTEGER, surveys_answered INTEGER, support_requests INTEGER)')
    conn.commit()
    conn.close()

# Функция добавления пользователя в БД


def add_user(user_id, username):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO users (id, username) VALUES (?, ?)", (user_id, username))
    conn.commit()
    conn.close()

# Получение списка пользователей


def get_users():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users")
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users

# Обновление статистики


def update_stat(column):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        f"INSERT INTO stats (date, {column}) VALUES (DATE('now'), 1) ON CONFLICT(date) DO UPDATE SET {column} = {column} + 1")
    conn.commit()
    conn.close()

# Команда /start


@dp.message_handler(commands=['start'])
async def start_command(message: types.Message):
    add_user(message.from_user.id, message.from_user.username)
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton("🆘 Поддержка"))
    await message.reply("Привет! Я бот, который будет отправлять вам материалы каждый день.", reply_markup=keyboard)

# Обратная связь


@dp.message_handler(lambda message: message.text == "🆘 Поддержка")
async def support_handler(message: types.Message):
    update_stat("support_requests")
    await message.reply("Напишите ваш вопрос, и мы ответим вам как можно скорее!")

# Рассылка материала


async def send_daily_material():
    users = get_users()
    for user in users:
        try:
            await bot.send_message(user, MATERIAL_TEXT)
        except:
            pass
    update_stat("materials_sent")

# Опрос в конце дня


async def send_daily_poll():
    users = get_users()
    for user in users:
        try:
            await bot.send_poll(user, POLL_QUESTION, POLL_OPTIONS, is_anonymous=False)
        except:
            pass
    update_stat("surveys_answered")

# Обработка ответов на опрос


@dp.poll_answer_handler()
async def poll_answer_handler(poll_answer: types.PollAnswer):
    update_stat("surveys_answered")

# Команда /stats (только для админа)


@dp.message_handler(commands=['stats'])
async def stats_command(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]

        cursor.execute(
            "SELECT SUM(materials_sent), SUM(surveys_answered), SUM(support_requests) FROM stats")
        result = cursor.fetchone()
        materials_sent = result[0] if result[0] else 0
        surveys_answered = result[1] if result[1] else 0
        support_requests = result[2] if result[2] else 0
        conn.close()

        stats_text = f"📊 *Статистика бота:*\n" \
            f"👥 *Пользователей всего:* {total_users}\n" \
            f"📩 *Материал получило:* {materials_sent}\n" \
            f"✅ *Ответило на опрос:* {surveys_answered}\n" \
            f"🆘 *Запросов в поддержку:* {support_requests}"

        await message.reply(stats_text, parse_mode="Markdown")
    else:
        await message.reply("⛔ Доступ запрещен!")

# Планировщик задач
scheduler.add_job(send_daily_material, "cron", hour=9,
                  minute=0)  # Материал в 9 утра
scheduler.add_job(send_daily_poll, "cron", hour=20, minute=0)  # Опрос в 20:00

if __name__ == '__main__':
    scheduler.start()
    executor.start_polling(dp, skip_updates=True)
