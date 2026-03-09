import asyncio
import logging
import os
import qrcode
from datetime import datetime
from io import BytesIO
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import FSInputFile, BufferedInputFile
from dotenv import load_dotenv
import database as db

# Загружаем переменные окружения
load_dotenv()

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", -1))
GOAL_AMOUNT = int(os.getenv("GOAL_AMOUNT", 700000))  # ✅ Цель: 700 000 ₽

# Реквизиты для оплаты (две карты)
PAYMENT_INFO = {
    "sber_card": "2202206825943553",      # Сбер
    "tinkoff_card": "2200701185988638",   # Тинькофф ← Новая карта
    "name": "Виталий Г",                   # ФИО получателя
}

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Создаём бота и диспетчер
bot = Bot(token=TOKEN)
dp = Dispatcher()


# --- ФУНКЦИЯ СОЗДАНИЯ QR-КОДА ---

def generate_qr_code(card_number: str, amount: int = None) -> BytesIO:
    """
    Создаёт QR-код для оплаты через СБП
    Возвращает изображение в памяти (BytesIO)
    """
    # Упрощённый формат для СБП
    if amount:
        qr_text = f"ST00012|Name={PAYMENT_INFO['name']}|PersonalAcc={card_number}|BankName=СБП|Sum={amount * 100}|Purpose=Донат на гараж"
    else:
        qr_text = f"ST00012|Name={PAYMENT_INFO['name']}|PersonalAcc={card_number}|BankName=СБП|Purpose=Донат на гараж"

    # Создаём QR-код
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_text)
    qr.make(fit=True)

    # Генерируем изображение
    img = qr.make_image(fill_color="black", back_color="white")

    # Сохраняем в память
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    return buffer


# --- КЛАВИАТУРЫ ---

def get_donation_keyboard():
    """Кнопки с суммами донатов"""
    builder = InlineKeyboardBuilder()
    builder.button(text="💰 100 ₽", callback_data="donate_100")
    builder.button(text="💰 300 ₽", callback_data="donate_300")
    builder.button(text="💰 500 ₽", callback_data="donate_500")
    builder.button(text="💰 1000 ₽", callback_data="donate_1000")
    builder.button(text="📱 QR-код", callback_data="show_qr")
    builder.button(text="✍️ Своя сумма", callback_data="donate_custom")
    builder.adjust(3, 2, 1)
    return builder.as_markup()

def get_main_keyboard():
    """Основная клавиатура"""
    builder = ReplyKeyboardBuilder()
    builder.button(text="📅 Афиша")
    builder.button(text="🎲 Случайное")
    builder.button(text="🏠 Гаражи")
    builder.button(text="❓ Помощь")
    builder.adjust(2, 2)
    return builder.as_markup(resize_keyboard=True)


def get_admin_keyboard():
    """Админ-панель"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика", callback_data="admin_stats")
    builder.button(text="📝 Добавить расход", callback_data="admin_expense")
    builder.button(text="📄 Отчёт за месяц", callback_data="admin_report")
    builder.adjust(3)
    return builder.as_markup()


def get_qr_keyboard():
    """Кнопки под сообщением с QR-кодом"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Другая сумма", callback_data="donate_custom")
    builder.button(text="📋 Инструкция", callback_data="qr_help")
    builder.adjust(2)
    return builder.as_markup()


# --- ОБРАБОТЧИКИ КОМАНД ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Главное меню"""
    total = await db.get_total_donations()
    progress = min(100, int((total / GOAL_AMOUNT) * 100))

    text = f"""
🚗 **Гараж Мечты — Проект покупки гаража**

Привет! Я коплю на покупку готового гаража в Екатеринбурге. Гаража мечты.

📊 **Прогресс сбора:**
{progress}% собрано ({total:,.0f} ₽ из {GOAL_AMOUNT:,.0f} ₽)

🔹 Все средства идут на покупку гаража
🔹 Ежемесячные отчёты в канале
🔹 🏠 Посмотреть варианты гаражей: кнопка «🏠 Гаражи» внизу

💙 Поддержи мою мечту!
Спасибо!
    """

    await message.answer(
        text,
        parse_mode="Markdown",
        reply_markup=get_donation_keyboard()
    )


@dp.message(Command("report"))
async def cmd_report(message: types.Message):
    """Публичный финансовый отчёт"""
    donations = await db.get_total_donations()
    expenses = await db.get_total_expenses()
    balance = donations - expenses

    text = f"""
📄 **Финансовый отчёт**

💰 **Пришло:** {donations:,.0f} ₽
💸 **Потрачено:** {expenses:,.0f} ₽
💳 **Остаток:** {balance:,.0f} ₽

📊 Прогресс: {(donations / GOAL_AMOUNT) * 100:.1f}%

Спасибо всем за поддержку! 
Пусть мечты сбываются.🙏
    """

    await message.answer(text, parse_mode="Markdown")


@dp.message(Command("garages"))
async def cmd_garages(message: types.Message):
    """Показать фотографии гаражей"""

    # Список фото с описаниями
    garages = [
        {
            "photo": "garage_1.jpg",
            "caption": "🏠 **Образец гаража №1**"
        },
        {
            "photo": "garage_2.jpg",
            "caption": "🏠 **Образец гаража №2**"
        },
        {
            "photo": "garage_3.jpg",
            "caption": "🏠 **Образец гаража №3**"
        },
        {
            "photo": "garage_4.jpg",
            "caption": "🏠 **Образец гаража №4**"
        }
    ]

    # Отправляем каждое фото
    for garage in garages:
        try:
            await message.answer_photo(
                photo=types.FSInputFile(garage["photo"]),
                caption=garage["caption"],
                parse_mode="Markdown"
            )
        except FileNotFoundError:
            await message.answer(f"❌ Фото {garage['photo']} не найдено!")

    await message.answer(
        "💙 Это варианты, которые я рассматриваю.\n"
        "Все средства идут на покупку одного из них!\n\n"
        "📊 Прогресс сбора: /report",
        parse_mode="Markdown"
    )

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    """Админ-панель (только для вас)"""
    if message.from_user.id != ADMIN_ID:
        await message.answer("🔐 Доступ только для администратора")
        return

    await message.answer(
        "⚙️ **Панель администратора**",
        parse_mode="Markdown",
        reply_markup=get_admin_keyboard()
    )


@dp.message(Command("qr"))
async def cmd_qr(message: types.Message):
    """Показать QR-код для доната"""
    await send_qr_message(message, amount=None)


# --- ОБРАБОТЧИКИ КНОПОК (CALLBACK) ---

@dp.callback_query(F.data.startswith("donate_"))
async def process_donation(callback: types.CallbackQuery):
    """Обработка выбора суммы доната"""
    await callback.answer()

    amount = callback.data.split("_")[1]

    if amount == "custom":
        await callback.message.answer(
            "✍️ **Введите сумму доната** (числом):\n\n"
            "Например: `750`\n"
            "Минимум: 10 ₽",
            parse_mode="Markdown"
        )
        return

    # Показываем реквизиты для выбранной суммы
    await send_payment_info(callback.message, amount=int(amount))


@dp.callback_query(F.data == "show_qr")
async def show_qr_code(callback: types.CallbackQuery):
    """Показать QR-код для оплаты"""
    await callback.answer()
    await send_qr_message(callback.message, amount=None)


@dp.callback_query(F.data == "qr_help")
async def qr_help(callback: types.CallbackQuery):
    """Инструкция по оплате через QR"""
    await callback.answer()

    help_text = """
📱 **Как оплатить через QR-код:**

1️⃣ Откройте приложение вашего банка
2️⃣ Нажмите «Оплата по QR» или «Сканировать»
3️⃣ Наведите камеру на код выше
4️⃣ Проверьте получателя: {name}
5️⃣ Введите сумму и подтвердите платёж

⚠️ После оплаты можете написать мне @VitaMon1

⚠️ **Важно:** 
- Это добровольное пожертвование (дарение)

Спасибо за поддержку! 🙏
    """.format(name=PAYMENT_INFO["name"])

    await callback.message.answer(help_text, parse_mode="Markdown")


@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    """Статистика для админа"""
    if callback.from_user.id != ADMIN_ID:
        return

    donations = await db.get_total_donations()
    expenses = await db.get_total_expenses()

    text = f"""
📊 **Статистика проекта**

💰 Донатов: {donations:,.0f} ₽
💳 Баланс: {donations - expenses:,.0f} ₽
🎯 Цель: {GOAL_AMOUNT:,.0f} ₽
📈 Прогресс: {(donations / GOAL_AMOUNT) * 100:.1f}%
    """

    await callback.message.answer(text, parse_mode="Markdown")


@dp.callback_query(F.data == "admin_report")
async def admin_report(callback: types.CallbackQuery):
    """Генерация отчёта за месяц"""
    if callback.from_user.id != ADMIN_ID:
        return

    donations = await db.get_all_donations()
    expenses = await db.get_all_expenses()

    report = "📄 **Отчёт за месяц**\n\n"

    report += "💰 **ДОХОДЫ:**\n"
    if donations:
        for d in donations[:10]:
            report += f"  • {d[4]}: {d[3]:,.0f} ₽ (@{d[2]})\n"
    else:
        report += "  (пока нет донатов)\n"

    report += "\n💸 **РАСХОДЫ:**\n"
    if expenses:
        for e in expenses[:10]:
            report += f"  • {e[3]}: {e[2]:,.0f} ₽ ({e[1]})\n"
    else:
        report += "  (пока нет расходов)\n"

    await callback.message.answer(report, parse_mode="Markdown")


# --- ОБРАБОТЧИКИ ТЕКСТОВЫХ КНОПОК ---

@dp.message(F.text == "🏠 Гаражи")
async def handle_garages_button(message: types.Message):
    """Обработка кнопки «🏠 Гаражи»"""
    await cmd_garages(message)


@dp.message(F.text == "❓ Помощь")
async def handle_help_button(message: types.Message):
    """Обработка кнопки «❓ Помощь»"""
    await cmd_help(message)


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Команда помощи"""
    help_text = """
📚 **Доступные команды:**

🔹 /start — начать
🔹 /help — это сообщение
🔹 /report — финансовый отчёт
🔹 /garages — посмотреть варианты гаражей
🔹 /qr — показать QR-код для оплаты

🎯 **Кнопки меню:**
🏠 Гаражи — показать 4 варианта
❓ Помощь — справка

💡 Или просто нажмите кнопку доната ниже!
    """
    await message.answer(help_text, parse_mode="Markdown")


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

async def send_payment_info(message: types.Message, amount: int):
    """Отправить реквизиты для оплаты (две карты)"""
    text = f"""
💰 **Донат {amount:,.0f} ₽**

Спасибо за поддержку! 🙏

**Реквизиты для перевода:**

🔹 **Сбер:** `{PAYMENT_INFO['sber_card']}`
🔹 **Тинькофф:** `{PAYMENT_INFO['tinkoff_card']}`
🔹 Получатель: {PAYMENT_INFO['name']}

📱 **Или отсканируйте QR-код:**
Нажмите кнопку «📱 QR-код» ниже.

⚠️ После оплаты напишите мне @VitaMon1
    """

    await message.answer(
        text,
        parse_mode="Markdown",
        reply_markup=get_donation_keyboard()
    )


async def send_qr_message(message: types.Message, amount: int = None):
    """Отправить сообщение с QR-кодом (для Сбера — основной)"""
    # Генерируем QR-код для основной карты (Сбер)
    qr_buffer = generate_qr_code(PAYMENT_INFO["sber_card"], amount)

    # Подпись к фото
    caption = f"""
📱 **QR-код для оплаты**

Отсканируйте код через приложение банка.

💳 Получатель: {PAYMENT_INFO['name']}
🔢 **Сбер:** `{PAYMENT_INFO['sber_card']}`
🔢 **Тинькофф:** `{PAYMENT_INFO['tinkoff_card']}`

⚠️ Если QR не сработал — введите карту вручную.
    """

    if amount:
        caption += f"\n💰 Сумма: {amount:,.0f} ₽"

    # Отправляем фото из памяти
    photo = BufferedInputFile(qr_buffer.read(), filename=f"qr_{amount or 'custom'}.png")

    await message.answer_photo(
        photo=photo,
        caption=caption,
        parse_mode="Markdown",
        reply_markup=get_qr_keyboard()
    )


# --- ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ ---

@dp.message(F.text)
async def handle_custom_amount(message: types.Message):
    """Обработка ввода своей суммы"""
    try:
        # Пробуем преобразовать текст в число
        amount = float(message.text.strip().replace(",", "."))

        if amount < 10:
            await message.answer("❌ Минимальная сумма — 10 ₽")
            return

        if amount > 100000:
            await message.answer("❌ Максимальная сумма — 100 000 ₽\nДля крупных сумм напишите мне лично.")
            return

        # Сохраняем донат в базу данных
        await db.add_donation(
            user_id=message.from_user.id,
            username=message.from_user.username or "Аноним",
            amount=amount,
            comment=f"Вручную: {message.text}"
        )

        # Отправляем подтверждение + реквизиты
        await message.answer(
            f"✅ **Донат {amount:,.0f} ₽ принят!**\n\n"
            f"Спасибо за поддержку! 🙏\n\n"
            f"**Реквизиты для перевода:**\n"
            f"🔹 **Сбер:** `{PAYMENT_INFO['sber_card']}`\n"
            f"🔹 **Тинькофф:** `{PAYMENT_INFO['tinkoff_card']}`\n"
            f"🔹 Получатель: {PAYMENT_INFO['name']}\n\n"
            f"⚠️ После оплаты напишите мне @VitaMon1",
            parse_mode="Markdown",
            reply_markup=get_donation_keyboard()
        )

        logger.info(f"💰 Донат: {amount:,.0f} ₽ от @{message.from_user.username or 'Аноним'}")

    except ValueError:
        # Если текст не число — просто эхо
        text = message.text
        if len(text) > 100:
            text = text[:97] + "..."

        await message.answer(f"🔁 Вы написали: {text}\n\n"
                             f"💡 Для доната нажмите кнопку ниже 👇",
                             reply_markup=get_donation_keyboard())


# --- ЗАПУСК БОТА ---

async def on_startup():
    """Действия при запуске"""
    await db.init_db()
    logger.info("🚀 Бот запущен!")

    # Устанавливаем команды в меню Telegram
    await bot.set_my_commands([
        types.BotCommand(command="start", description="🚀 Начать"),
        types.BotCommand(command="report", description="📊 Финансовый отчёт"),
        types.BotCommand(command="garages", description="🏠 Варианты гаражей"),
        types.BotCommand(command="qr", description="📱 QR-код для оплаты"),
        types.BotCommand(command="help", description="❓ Помощь"),
        types.BotCommand(command="admin", description="⚙️ Админ-панель"),
    ])
    logger.info("✅ Команды обновлены в Telegram")


async def main():
    """Точка входа"""
    await on_startup()
    logger.info("✅ Начинаю опрос сервера Telegram...")

    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("🛑 Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
    finally:
        await bot.session.close()
        logger.info("🔌 Сессия бота закрыта")


if __name__ == "__main__":
    asyncio.run(main())