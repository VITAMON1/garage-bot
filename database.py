import aiosqlite
from datetime import datetime

DB_NAME = 'donations.db'

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS donations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            amount REAL,
            comment TEXT,
            date TEXT
        )''')
        await db.execute('''CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT,
            amount REAL,
            receipt_url TEXT,
            date TEXT
        )''')
        await db.commit()

async def add_donation(user_id, username, amount, comment=""):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            'INSERT INTO donations (user_id, username, amount, comment, date) VALUES (?, ?, ?, ?, ?)',
            (user_id, username, amount, comment, datetime.now().strftime('%Y-%m-%d %H:%M'))
        )
        await db.commit()

async def add_expense(description, amount, receipt_url=""):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            'INSERT INTO expenses (description, amount, receipt_url, date) VALUES (?, ?, ?, ?)',
            (description, amount, receipt_url, datetime.now().strftime('%Y-%m-%d %H:%M'))
        )
        await db.commit()

async def get_total_donations():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute('SELECT SUM(amount) FROM donations')
        result = await cursor.fetchone()
        return result[0] or 0

async def get_total_expenses():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute('SELECT SUM(amount) FROM expenses')
        result = await cursor.fetchone()
        return result[0] or 0

async def get_all_donations():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute('SELECT * FROM donations ORDER BY date DESC')
        return await cursor.fetchall()

async def get_all_expenses():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute('SELECT * FROM expenses ORDER BY date DESC')
        return await cursor.fetchall()

# --- Новые методы ---

async def get_top_donors(limit):
    """Возвращает топ доноров по общей сумме взносов."""
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            '''SELECT user_id, username, SUM(amount) as total_amount 
               FROM donations 
               GROUP BY user_id 
               ORDER BY total_amount DESC 
               LIMIT ?''',
            (limit,)
        )
        return await cursor.fetchall()

async def get_user_donations(user_id):
    """Возвращает все донаты конкретного пользователя."""
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            'SELECT * FROM donations WHERE user_id = ? ORDER BY date DESC',
            (user_id,)
        )
        return await cursor.fetchall()

async def get_user_total_donations(user_id):
    """Возвращает общую сумму донатов конкретного пользователя."""
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            'SELECT SUM(amount) FROM donations WHERE user_id = ?',
            (user_id,)
        )
        result = await cursor.fetchone()
        return result[0] or 0