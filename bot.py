import logging
import os
import httpx
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# Логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Получаем токен и URL из переменных окружения Render
TOKEN = os.getenv("BOT_TOKEN")
APP_URL = os.getenv("RENDER_EXTERNAL_URL").rstrip("/")

# Константы
SERVICE_FEE = 2000
CBR_API_URL = "https://www.cbr-xml-daily.ru/daily_json.js"
PRICE, BOX = range(2)

BOX_TYPES = {
    "MINI (футболка, сумка, ремень, носки)": {
        "size": "23×17×13 см",
        "delivery_price": 1200,
        "short": "MINI"
    },
    "SMALL (пара обуви в коробке)": {
        "size": "36×26×14 см",
        "delivery_price": 2000,
        "short": "SMALL"
    },
    "LARGE (пара обуви и несколько вещей)": {
        "size": "40×29×16 см",
        "delivery_price": 2900,
        "short": "LARGE"
    },
    "XXL (две пары обуви и вещи)": {
        "size": "37×29×28 см",
        "delivery_price": 4000,
        "short": "XXL"
    }
}

def get_box_keyboard():
    return ReplyKeyboardMarkup(
        [[box_type] for box_type in BOX_TYPES.keys()],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def format_price(price: float) -> str:
    return f"{int(price):,} ₽".replace(",", " ")

async def get_cny_rate() -> float:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(CBR_API_URL)
            response.raise_for_status()
            data = response.json()
            cny_rate = data['Valute']['CNY']['Value'] / data['Valute']['CNY']['Nominal']
            return round(cny_rate, 2)
    except Exception as e:
        logger.error(f"Ошибка получения курса: {e}")
        return 12.5

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "👟 Введите цену товара в юанях (CNY):\nПример: 1500",
        reply_markup=ReplyKeyboardMarkup([["/cancel"]], resize_keyboard=True)
    )
    return PRICE

async def handle_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "/cancel":
        return await cancel(update, context)
    try:
        price = float(text.replace(",", "."))
        if price <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Введите корректную цену (например: 1500)")
        return PRICE

    cny_rate = await get_cny_rate()
    context.user_data.update({'price': price, 'cny_rate': cny_rate})
    await update.message.reply_text(
        f"📦 Выберите коробку (курс: 1 CNY = {cny_rate} RUB):",
        reply_markup=get_box_keyboard()
    )
    return BOX

async def handle_box(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "/cancel":
        return await cancel(update, context)
    if text not in BOX_TYPES:
        await update.message.reply_text("❌ Выберите вариант из списка:", reply_markup=get_box_keyboard())
        return BOX

    box_data = BOX_TYPES[text]
    price_cny = context.user_data['price']
    cny_rate = context.user_data['cny_rate']
    price_rub = price_cny * cny_rate
    delivery_price = box_data['delivery_price']
    total = price_rub + delivery_price + SERVICE_FEE

    result = (
        f"📊 *Итоговый расчет*\n\n"
        f"📦 {text}\n"
        f"• Размер: {box_data['size']}\n"
        f"• Доставка: {format_price(delivery_price)}\n\n"
        f"💵 Товар: {format_price(price_rub)}\n"
        f"(Цена: {price_cny} CNY × Курс: {cny_rate} RUB)\n\n"
        f"💼 Комиссия: {format_price(SERVICE_FEE)}\n"
        f"══════════════════\n"
        f"💳 *Итого: {format_price(total)}*"
    )

    await update.message.reply_text(
        result,
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True)
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "❌ Отменено. Для нового расчета /start",
        reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True)
    )
    return ConversationHandler.END

# Установка webhook
async def set_webhook(application: Application):
    webhook_url = f"{APP_URL}/webhook/{TOKEN}"
    try:
        await application.bot.set_webhook(webhook_url)
        logger.info(f"Webhook установлен: {webhook_url}")
    except Exception as e:
        logger.error(f"Ошибка установки webhook: {e}")

def main():
    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_price)],
            BOX: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_box)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)

    logger.info("Бот запущен через Webhook")
    try:
        app.run_webhook(
            listen="0.0.0.0",
            port=int(os.environ.get("PORT", 8443)),
            webhook_url=f"{APP_URL}/webhook/{TOKEN}",
            on_startup=set_webhook
        )
    except Exception as e:
        logger.error(f"Ошибка запуска webhook: {e}")

if __name__ == "__main__":
    main()
