import asyncio
import logging
import os
import csv
import qrcode
from datetime import datetime
from io import BytesIO, StringIO
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
GOAL_AMOUNT = int(os.getenv("GOAL_AMOUNT", 700000))  # Цель: 700 000 ₽
CHANNEL_ID = os.getenv("CHANNEL_ID", "")  # ID канала для уведомлений (опционально)

# Реквизиты для оплаты (две карты) — БЕЗ ПРОБЕЛОВ!
PAYMENT_INFO = {
    "sber_card": "2202206825943553",  # Сбер без пробелов
    "tinkoff_card": "2200701185988638",  # Тинькофф без пробелов
    "name": "Виталий Г",  # ФИО получателя
}

# Уровни доноров
DONOR_TIERS = {
    5000: {"name": "👑 Легенда гаража", "emoji": "👑"},
    2000: {"name": "⚙️ Мастер", "emoji": "⚙️"},
    500: {"name": "🔧 Помощник", "emoji": "🔧"},
}

# Контрольные точки (milestones)
MILESTONES = [100000, 250000, 500000, 700000]

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Отдельный логгер для донатов
donation_logger = logging.getLogger("donations")
donation_handler = logging.FileHandler("donations.log", encoding="utf-8")
donation_handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
donation_logger.addHandler(donation_handler)
donation_logger.setLevel(logging.INFO)

# Создаём бота и диспетчер
bot = Bot(token=TOKEN)
dp = Dispatcher()


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def format_card(card: str) -> str:
    """Форматирует номер карты для красивого отображения"""
    return ' '.join(card[i:i + 4] for i in range(0, len(card), 4))


def format_progress(current: int, goal: int, length: int = 20) -> str:
    """Создаёт визуальный прогресс-бар"""
    if current >= goal:
        bar = "🟩" * length
        percent = 100
    else:
        filled = int(length * current / goal)
        bar = "🟩" * filled + "⬜️" * (length - filled)
        percent = min(100, int((current / goal) * 100))

    return f"{bar}\n{percent}% ({current:,.0f} / {goal:,.0f} ₽)"


def get_donor_status(total_donated: int) -> str:
    """Определяет статус донора по сумме пожертвований"""
    for threshold in sorted(DONOR_TIERS.keys(), reverse=True):
        if total_donated >= threshold:
            return DONOR_TIERS[threshold]["name"]
    return "👤 Гость"


async def check_milestones(old_total: int, new_total: int):
    """Проверяет достижение контрольных точек и отправляет уведомления"""
    if not CHANNEL_ID:
        return

    for milestone in MILESTONES:
        if old_total < milestone <= new_total:
            try:
                await bot.send_message(
                    CHANNEL_ID,
                    f"🎉 **НОВЫЙ РУБЕЖ!**\n\n"
                    f"Мы собрали **{milestone:,.0f} ₽**!\n"
                    f"Это {int((milestone / GOAL_AMOUNT) * 100)}% от цели!\n\n"
                    f"Спасибо всем за поддержку! Вместе мы ближе к мечте! 🚗💨\n\n"
                    f"#ГаражМечты #Милстоун",
                    parse_mode="Markdown"
                )
                logger.info(f"✅ Отправлено уведомление о milestone: {milestone}")
            except Exception as e:
                logger.error(f"❌ Ошибка отправки уведомления о milestone: {e}")


def generate_qr_code(card_number: str, amount: int = None) -> BytesIO:
    """Создаёт QR-код для оплаты через СБП"""
    if amount:
        qr_text = f"ST00012|Name={PAYMENT_INFO['name']}|PersonalAcc={card_number}|BankName=СБП|Sum={amount * 100}|Purpose=Донат на гараж"
    else:
        qr_text = f"ST00012|Name={PAYMENT_INFO['name']}|PersonalAcc={card_number}|BankName=СБП|Purpose=Донат на гараж"

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_text)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

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
    builder.button(text="📥 Скачать CSV", callback_data="admin_export")
    builder.adjust(2, 2)
    return builder.as_markup()


def get_qr_keyboard():
    """Кнопки под сообщением с QR-кодом"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Другая сумма", callback_data="donate_custom")
    builder.button(text="📋 Инструкция", callback_data="qr_help")
    builder.adjust(2)
    return builder.as_markup()


def get_copy_card_keyboard():
    """Кнопки для копирования номеров карт"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Скопировать Сбер", callback_data="copy_sber")
    builder.button(text="📋 Скопировать Тинькофф", callback_data="copy_tinkoff")
    builder.adjust(2)
    return builder.as_markup()


# --- ОБРАБОТЧИКИ КОМАНД ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Главное меню"""
    total = await db.get_total_donations()

    # Получаем статус донора если пользователь уже жертвовал
    user_status = "👤 Гость"
    if message.from_user.id:
        user_total = await db.get_user_donations(message.from_user.id)
        if user_total > 0:
            user_status = get_donor_status(user_total)

    text = f"""
🚗 **Гараж Мечты — Проект покупки гаража**

Привет{', ' + user_status if user_status != '👤 Гость' else ''}! Я с детства люблю чинить машины своими руками. Но делать это на улице — не самое удобное занятие. ❄️🌧

Моя мечта — собственный гараж в Екатеринбурге. Там я смогу комфортно ремонтировать машину и хранить всё необходимое.

Я коплю на покупку готового гаража. Любая поддержка приблизит меня к цели!

💙 Спасибо, что вы со мной! Пусть мечты сбываются.

💰 На что пойдут ваши донаты:
✓ Оформление документов и нотариус
✓ Первый взнос или полная оплата гаража
✓ Минимальный ремонт: свет, розетки, вентиляция

🎁 Что вы получите взамен:
• Именной статус в боте: «Помощник», «Мастер», «Легенда гаража»
• Персональная благодарность с упоминанием в канале

📊 **Прогресс сбора:**
{format_progress(total, GOAL_AMOUNT)}

🔹 Все средства идут на покупку гаража
🔹 Ежемесячные отчёты в канале
🔹 🏠 Посмотреть варианты гаражей: кнопка «🏠 Гаражи» внизу

💙 Поддержи мою мечту!
Спасибо!

⚠️ **Важно:** все переводы являются добровольными пожертвованиями (дарением) в соответствии со ст. 582 ГК РФ. Возврат средств не предусмотрен. Средства не являются оплатой товаров или услуг.
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

📊 Прогресс: 
{format_progress(donations, GOAL_AMOUNT)}

🏆 **Топ-5 помощников:**
{await get_top_donors_text()}

Спасибо всем за поддержку!
Пусть мечты сбываются. 🙏

⚠️ Все переводы — добровольные пожертвования (ст. 582 ГК РФ).
    """

    await message.answer(text, parse_mode="Markdown")


@dp.message(Command("top"))
async def cmd_top(message: types.Message):
    """Показать топ доноров"""
    text = f"🏆 **Топ помощников проекта**\n\n{await get_top_donors_text()}"
    await message.answer(text, parse_mode="Markdown")


async def get_top_donors_text(limit: int = 5) -> str:
    """Получает текст с топ донорами"""
    try:
        top_donors = await db.get_top_donors(limit)

        if not top_donors:
            return "_(Пока нет донатов. Будь первым!)_"

        result = ""
        for i, donor in enumerate(top_donors, 1):
            username = donor[0] if donor[0] else "Аноним"
            amount = donor[1]
            status = get_donor_status(amount)

            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            result += f"{medal} {username} — {amount:,.0f} ₽ {status}\n"

        return result
    except Exception as e:
        logger.error(f"Ошибка получения топ доноров: {e}")
        return "_(Не удалось загрузить топ)_"


@dp.message(Command("garages"))
async def cmd_garages(message: types.Message):
    """Показать фотографии гаражей"""
    garages = [
        {"photo": "garage_1.jpg", "caption": "🏠 **Образец гаража №1**"},
        {"photo": "garage_2.jpg", "caption": "🏠 **Образец гаража №2**"},
        {"photo": "garage_3.jpg", "caption": "🏠 **Образец гаража №3**"},
        {"photo": "garage_4.jpg", "caption": "🏠 **Образец гаража №4**"}
    ]

    for garage in garages:
        try:
            await message.answer_photo(
                photo=types.FSInputFile(garage["photo"]),
                caption=garage["caption"],
                parse_mode="Markdown"
            )
        except FileNotFoundError:
            logger.error(f"❌ Фото не найдено: {garage['photo']}")
            await message.answer(f"❌ Фото {garage['photo']} не найдено!")

    await message.answer(
        "💙 Это варианты гаражей, которые я рассматриваю.\n"
        "Все средства идут на покупку одного из них!\n\n"
        "📊 Прогресс сбора: /report",
        parse_mode="Markdown"
    )


@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    """Админ-панель (только для админа)"""
    if message.from_user.id != ADMIN_ID:
        logger.warning(f"Попытка доступа к /admin от пользователя {message.from_user.id}")
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

    amount_int = int(amount)
    await send_payment_info(callback.message, amount=amount_int)


@dp.callback_query(F.data == "show_qr")
async def show_qr_code(callback: types.CallbackQuery):
    """Показать QR-код для оплаты"""
    await callback.answer()
    await send_qr_message(callback.message, amount=None)


@dp.callback_query(F.data == "copy_sber")
async def copy_sber(callback: types.CallbackQuery):
    """Копирование номера карты Сбера"""
    card_formatted = format_card(PAYMENT_INFO['sber_card'])
    await callback.answer(
        f"📋 Номер карты Сбербанк:\n{card_formatted}\n\n"
        f"Нажмите и удерживайте, чтобы скопировать",
        show_alert=True
    )


@dp.callback_query(F.data == "copy_tinkoff")
async def copy_tinkoff(callback: types.CallbackQuery):
    """Копирование номера карты Тинькофф"""
    card_formatted = format_card(PAYMENT_INFO['tinkoff_card'])
    await callback.answer(
        f"📋 Номер карты Тинькофф:\n{card_formatted}\n\n"
        f"Нажмите и удерживайте, чтобы скопировать",
        show_alert=True
    )


@dp.callback_query(F.data == "qr_help")
async def qr_help(callback: types.CallbackQuery):
    """Инструкция по оплате через QR"""
    await callback.answer()

    help_text = f"""
📱 **Как оплатить через QR-код:**

1️⃣ Откройте приложение вашего банка
2️⃣ Нажмите «Оплата по QR» или «Сканировать»
3️⃣ Наведите камеру на код выше
4️⃣ Проверьте получателя: {PAYMENT_INFO['name']}
5️⃣ Введите сумму и подтвердите платёж

⚠️ После оплаты можете написать мне @VitaMon1

⚠️ **Важно:**
- Это добровольное пожертвование (дарение)
- Возврат средств не предусмотрен

Спасибо за поддержку! 🙏
    """

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
📈 Прогресс: 
{format_progress(donations, GOAL_AMOUNT)}
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


@dp.callback_query(F.data == "admin_export")
async def export_donations(callback: types.CallbackQuery):
    """Экспорт донатов в CSV"""
    if callback.from_user.id != ADMIN_ID:
        return

    try:
        donations = await db.get_all_donations()

        # Создаём CSV в памяти
        output = StringIO()
        writer = csv.writer(output)

        # Заголовок
        writer.writerow(['ID', 'User ID', 'Username', 'Amount', 'Date', 'Comment'])

        # Данные
        for d in donations:
            writer.writerow([d[0], d[1], d[2], d[3], d[4], d[5]])

        # Получаем байты
        csv_content = output.getvalue().encode('utf-8-sig')  # UTF-8-SIG для Excel
        output.close()

        # Формируем имя файла
        filename = f"donations_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        # Отправляем файл
        file = BufferedInputFile(csv_content, filename=filename)
        await callback.message.answer_document(
            document=file,
            caption=f"📥 **Экспорт донатов**\n\nВсего записей: {len(donations)}"
        )

        logger.info(f"✅ Админ {callback.from_user.id} экспортировал донаты ({len(donations)} записей)")

    except Exception as e:
        logger.error(f"❌ Ошибка экспорта CSV: {e}")
        await callback.message.answer("❌ Ошибка при экспорте данных")


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
🔹 /report — финансовый отчёт + топ доноров
🔹 /top — топ помощников проекта
🔹 /garages — посмотреть варианты гаражей
🔹 /qr — показать QR-код для оплаты
🔹 /admin — панель администратора

🎯 **Кнопки меню:**
🏠 Гаражи — показать 4 варианта
❓ Помощь — справка

💡 Или просто нажмите кнопку доната ниже!

⚠️ Все переводы — добровольные пожертвования (ст. 582 ГК РФ).
    """
    await message.answer(help_text, parse_mode="Markdown")


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

async def send_payment_info(message: types.Message, amount: int):
    """Отправить реквизиты для оплаты (две карты)"""
    text = f"""
💰 **Донат {amount:,.0f} ₽**

Спасибо за поддержку! 🙏

**Реквизиты для перевода:**

🔹 **Сбер:** `{format_card(PAYMENT_INFO['sber_card'])}`
🔹 **Тинькофф:** `{format_card(PAYMENT_INFO['tinkoff_card'])}`
🔹 Получатель: {PAYMENT_INFO['name']}

📱 **Или отсканируйте QR-код:**
Нажмите кнопку «📱 QR-код» ниже.

⚠️ После оплаты напишите мне @VitaMon1

⚠️ **Важно:** перевод является добровольным пожертвованием (ст. 582 ГК РФ).
    """

    await message.answer(
        text,
        parse_mode="Markdown",
        reply_markup=get_copy_card_keyboard()
    )


async def send_qr_message(message: types.Message, amount: int = None):
    """Отправить сообщение с QR-кодом"""
    qr_buffer = generate_qr_code(PAYMENT_INFO["sber_card"], amount)

    caption = f"""
📱 **QR-код для оплаты**

Отсканируйте код через приложение банка.

💳 Получатель: {PAYMENT_INFO['name']}
🔢 **Сбер:** `{format_card(PAYMENT_INFO['sber_card'])}`
🔢 **Тинькофф:** `{format_card(PAYMENT_INFO['tinkoff_card'])}`

⚠️ Если QR не сработал — введите карту вручную.
⚠️ Это добровольное пожертвование (ст. 582 ГК РФ).
    """

    if amount:
        caption += f"\n💰 Сумма: {amount:,.0f} ₽"

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
        amount = float(message.text.strip().replace(",", "."))

        if amount < 10:
            await message.answer("❌ Минимальная сумма — 10 ₽")
            return

        if amount > 100000:
            await message.answer("❌ Максимальная сумма — 100 000 ₽\nДля крупных сумм напишите мне лично.")
            return

        # Получаем текущую сумму до доната
        old_total = await db.get_total_donations()

        # Сохраняем донат в базу данных
        await db.add_donation(
            user_id=message.from_user.id,
            username=message.from_user.username or "Аноним",
            amount=amount,
            comment=f"Вручную: {message.text}"
        )

        # Получаем новую сумму после доната
        new_total = await db.get_total_donations()

        # Проверяем milestone'ы
        await check_milestones(old_total, new_total)

        # Определяем статус донора
        user_total = await db.get_user_donations(message.from_user.id)
        status = get_donor_status(user_total)

        # Отправляем подтверждение + реквизиты
        await message.answer(
            f"✅ **Донат {amount:,.0f} ₽ принят!**\n\n"
            f"Ваш статус: {status}\n"
            f"Спасибо за поддержку! 🙏\n\n"
            f"**Реквизиты для перевода:**\n"
            f"🔹 **Сбер:** `{format_card(PAYMENT_INFO['sber_card'])}`\n"
            f"🔹 **Тинькофф:** `{format_card(PAYMENT_INFO['tinkoff_card'])}`\n"
            f"🔹 Получатель: {PAYMENT_INFO['name']}\n\n"
            f"⚠️ После оплаты напишите мне @VitaMon1\n\n"
            f"⚠️ Перевод является добровольным пожертвованием (ст. 582 ГК РФ).",
            parse_mode="Markdown",
            reply_markup=get_copy_card_keyboard()
        )

        # Логирование в отдельный файл
        donation_logger.info(
            f"💰 Донат: {amount:,.0f} ₽ от @{message.from_user.username or 'Аноним'} (ID: {message.from_user.id})")

        # Логирование в основной лог
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

    # Проверка настроек
    if ADMIN_ID == -1:
        logger.warning("⚠️ ADMIN_ID не настроен! Команда /admin не будет работать.")
    else:
        logger.info(f"✅ ADMIN_ID настроен: {ADMIN_ID}")

    if not CHANNEL_ID:
        logger.info("ℹ️ CHANNEL_ID не настроен. Уведомления о milestone отключены.")
    else:
        logger.info(f"✅ CHANNEL_ID настроен: {CHANNEL_ID}")

    logger.info("🚀 Бот запущен!")
    logger.info("📝 Донаты логируются в файл: donations.log")

    # Устанавливаем команды в меню Telegram
    await bot.set_my_commands([
        types.BotCommand(command="start", description="🚀 Начать"),
        types.BotCommand(command="report", description="📊 Отчёт + топ"),
        types.BotCommand(command="top", description="🏆 Топ доноров"),
        types.BotCommand(command="garages", description="🏠 Варианты гаражей"),
        types.BotCommand(command="qr", description="📱 QR-код"),
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