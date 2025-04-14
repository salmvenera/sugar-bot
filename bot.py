import os
import logging
from datetime import datetime, time
from typing import Dict, Optional

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils import executor
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import sqlite3

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация бота
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_ID = os.getenv('TELEGRAM_ADMIN_ID')  # ID администратора для статистики

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Планировщик для ежедневных рассылок
scheduler = AsyncIOScheduler()

# Инициализация базы данных


def init_db():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()

    # Таблица пользователей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        registered_at TEXT,
        last_active_at TEXT,
        materials_received INTEGER DEFAULT 0,
        materials_read INTEGER DEFAULT 0,
        polls_answered INTEGER DEFAULT 0,
        feedback_requests INTEGER DEFAULT 0
    )
    ''')

    # Таблица опросов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS polls (
        poll_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        question TEXT,
        answer TEXT,
        answered_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    ''')

    # Таблица материалов
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS materials (
        material_id INTEGER PRIMARY KEY AUTOINCREMENT,
        sent_at TEXT,
        read_count INTEGER DEFAULT 0
    )
    ''')

    conn.commit()
    conn.close()


init_db()

# Клавиатура для основного меню


def get_main_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton("📝 Обратная связь"))
    keyboard.add(KeyboardButton("📊 Статистика (для админа)"))
    return keyboard

# Клавиатура для обратной связи


def get_feedback_keyboard():
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton(
        "Написать сообщение", callback_data="feedback_message"))
    keyboard.add(InlineKeyboardButton(
        "Отмена", callback_data="feedback_cancel"))
    return keyboard

# Обработчик команды /start


@dp.message_handler(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    now = datetime.now().isoformat()

    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()

    # Проверяем, есть ли пользователь в базе
    cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
    user_exists = cursor.fetchone()

    if not user_exists:
        # Регистрируем нового пользователя
        cursor.execute('''
        INSERT INTO users (user_id, username, first_name, last_name, registered_at, last_active_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, last_name, now, now))
        conn.commit()
        logger.info(f"New user registered: {user_id} ({username})")

        await message.answer("👋 Добро пожаловать! Вы успешно зарегистрированы.", reply_markup=get_main_keyboard())
    else:
        # Обновляем время последней активности
        cursor.execute(
            'UPDATE users SET last_active_at = ? WHERE user_id = ?', (now, user_id))
        conn.commit()
        logger.info(f"User returned: {user_id} ({username})")

        await message.answer("👋 С возвращением!", reply_markup=get_main_keyboard())

    conn.close()

# Ежедневная рассылка материалов


async def send_daily_material():
    # Здесь должен быть ваш материал для рассылки
    material_text = "📚 Ваш ежедневный материал:\n\nСегодня мы изучаем... (здесь ваш контент)"

    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()

    # Записываем факт отправки материала
    sent_at = datetime.now().isoformat()
    cursor.execute('INSERT INTO materials (sent_at) VALUES (?)', (sent_at,))
    material_id = cursor.lastrowid

    # Получаем всех активных пользователей
    cursor.execute(
        'SELECT user_id FROM users WHERE last_active_at > date("now", "-30 days")')
    users = cursor.fetchall()

    for (user_id,) in users:
        try:
            await bot.send_message(user_id, material_text)

            # Обновляем счетчик материалов у пользователя
            cursor.execute('''
            UPDATE users
            SET materials_received = materials_received + 1
            WHERE user_id = ?
            ''', (user_id,))

            logger.info(f"Material sent to user: {user_id}")
        except Exception as e:
            logger.error(f"Failed to send material to {user_id}: {e}")

    conn.commit()
    conn.close()

# Ежедневный опрос


async def send_daily_poll():
    # Здесь должен быть ваш опрос
    question = "Как вам сегодняшний материал?"
    options = ["Отлично", "Хорошо", "Нормально", "Плохо", "Очень плохо"]

    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()

    # Получаем всех активных пользователей
    cursor.execute(
        'SELECT user_id FROM users WHERE last_active_at > date("now", "-30 days")')
    users = cursor.fetchall()

    for (user_id,) in users:
        try:
            await bot.send_poll(
                chat_id=user_id,
                question=question,
                options=options,
                is_anonymous=False
            )
            logger.info(f"Poll sent to user: {user_id}")
        except Exception as e:
            logger.error(f"Failed to send poll to {user_id}: {e}")

    conn.close()

# Обработчик ответов на опросы


@dp.poll_answer_handler()
async def handle_poll_answer(poll_answer: types.PollAnswer):
    user_id = poll_answer.user.id
    answer = poll_answer.option_ids[0]  # индекс выбранного варианта
    now = datetime.now().isoformat()

    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()

    # Записываем ответ
    cursor.execute('''
    INSERT INTO polls (user_id, question, answer, answered_at)
    VALUES (?, ?, ?, ?)
    ''', (user_id, "Как вам сегодняшний материал?", answer, now))

    # Обновляем счетчик опросов у пользователя
    cursor.execute('''
    UPDATE users
    SET polls_answered = polls_answered + 1,
        last_active_at = ?
    WHERE user_id = ?
    ''', (now, user_id))

    conn.commit()
    conn.close()
    logger.info(f"User {user_id} answered poll with option {answer}")

# Обработчик кнопки обратной связи


@dp.message_handler(lambda message: message.text == "📝 Обратная связь")
async def feedback_button(message: types.Message):
    await message.answer(
        "Выберите действие:",
        reply_markup=get_feedback_keyboard()
    )

# Обработчик inline кнопок обратной связи


@dp.callback_query_handler(lambda c: c.data.startswith('feedback_'))
async def process_feedback(callback_query: types.CallbackQuery, state: FSMContext):
    if callback_query.data == "feedback_message":
        await bot.answer_callback_query(callback_query.id)
        await bot.send_message(
            callback_query.from_user.id,
            "Напишите ваше сообщение для обратной связи:"
        )
        await state.set_state("waiting_for_feedback")
    elif callback_query.data == "feedback_cancel":
        await bot.answer_callback_query(callback_query.id)
        await bot.send_message(
            callback_query.from_user.id,
            "Обратная связь отменена.",
            reply_markup=get_main_keyboard()
        )
        await state.finish()

# Обработчик текста обратной связи


@dp.message_handler(state="waiting_for_feedback")
async def process_feedback_message(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    now = datetime.now().isoformat()

    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()

    # Обновляем счетчик обратной связи
    cursor.execute('''
    UPDATE users
    SET feedback_requests = feedback_requests + 1,
        last_active_at = ?
    WHERE user_id = ?
    ''', (now, user_id))

    conn.commit()
    conn.close()

    # Отправляем сообщение админу
    if ADMIN_ID:
        try:
            await bot.send_message(
                ADMIN_ID,
                f"📩 Новое сообщение от пользователя {message.from_user.username} (ID: {user_id}):\n\n{message.text}"
            )
        except Exception as e:
            logger.error(f"Failed to send feedback to admin: {e}")

    await message.answer(
        "Спасибо за ваше сообщение! Мы обязательно его рассмотрим.",
        reply_markup=get_main_keyboard()
    )
    await state.finish()
    logger.info(f"Feedback received from user {user_id}")

# Обработчик команды /stats (только для админа)


@dp.message_handler(Command("stats"), user_id=ADMIN_ID)
async def cmd_stats(message: types.Message):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()

    # Общая статистика
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]

    cursor.execute(
        'SELECT COUNT(*) FROM users WHERE last_active_at > date("now", "-1 days")')
    active_today = cursor.fetchone()[0]

    cursor.execute(
        'SELECT COUNT(*) FROM users WHERE last_active_at > date("now", "-7 days")')
    active_week = cursor.fetchone()[0]

    cursor.execute(
        'SELECT COUNT(*) FROM users WHERE registered_at > date("now", "-1 days")')
    new_today = cursor.fetchone()[0]

    cursor.execute(
        'SELECT COUNT(*) FROM users WHERE registered_at > date("now", "-7 days")')
    new_week = cursor.fetchone()[0]

    # Статистика материалов
    cursor.execute('SELECT COUNT(*) FROM materials')
    total_materials = cursor.fetchone()[0]

    cursor.execute(
        'SELECT AVG(read_count) FROM (SELECT materials_received FROM users WHERE materials_received > 0)')
    avg_materials_read = cursor.fetchone()[0] or 0

    # Статистика опросов
    cursor.execute('SELECT COUNT(*) FROM polls')
    total_polls = cursor.fetchone()[0]

    cursor.execute(
        'SELECT answer, COUNT(*) FROM polls GROUP BY answer ORDER BY COUNT(*) DESC')
    poll_answers = cursor.fetchall()

    # Статистика обратной связи
    cursor.execute('SELECT COUNT(*) FROM users WHERE feedback_requests > 0')
    feedback_users = cursor.fetchone()[0]

    conn.close()

    # Формируем сообщение со статистикой
    stats_message = (
        "📊 Статистика бота:\n\n"
        f"👥 Пользователи:\n"
        f"- Всего: {total_users}\n"
        f"- Активных за сегодня: {active_today}\n"
        f"- Активных за неделю: {active_week}\n"
        f"- Новых за сегодня: {new_today}\n"
        f"- Новых за неделю: {new_week}\n\n"
        f"📚 Материалы:\n"
        f"- Всего отправлено: {total_materials}\n"
        f"- Среднее прочтение на пользователя: {avg_materials_read:.1f}\n\n"
        f"📝 Опросы:\n"
        f"- Всего ответов: {total_polls}\n"
        f"- Распределение ответов:\n"
    )

    for answer, count in poll_answers:
        stats_message += f"  {answer+1}. {['Отлично', 'Хорошо', 'Нормально', 'Плохо', 'Очень плохо'][answer]}: {count}\n"

    stats_message += (
        f"\n📩 Обратная связь:\n"
        f"- Пользователей оставивших отзыв: {feedback_users}\n"
    )

    await message.answer(stats_message)

# Обработчик прочтения сообщений


@dp.message_handler(content_types=types.ContentType.ANY)
async def track_message_read(message: types.Message):
    if message.from_user.id == ADMIN_ID and message.text == "📊 Статистика (для админа)":
        await cmd_stats(message)
        return

    # Обновляем время последней активности
    user_id = message.from_user.id
    now = datetime.now().isoformat()

    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()

    cursor.execute('''
    UPDATE users
    SET last_active_at = ?
    WHERE user_id = ?
    ''', (now, user_id))

    conn.commit()
    conn.close()

# Запуск планировщика


def schedule_jobs():
    # Ежедневная рассылка материала в 10:00
    scheduler.add_job(
        send_daily_material,
        CronTrigger(hour=10, minute=0),
        name="daily_material"
    )

    # Ежедневный опрос в 20:00
    scheduler.add_job(
        send_daily_poll,
        CronTrigger(hour=20, minute=0),
        name="daily_poll"
    )

    scheduler.start()
    logger.info("Scheduler started")


# Запуск бота
if __name__ == '__main__':
    schedule_jobs()
    executor.start_polling(dp, skip_updates=True)
