import logging
import os
import httpx
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Конфигурация
TOKEN = os.getenv("BOT_TOKEN")
APP_URL = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
SERVICE_FEE = 2000
CBR_API_URL = "https://www.cbr-xml-daily.ru/daily_json.js"
PRICE, BOX = range(2)

BOX_TYPES = {
    "MINI (футболка, сумка, ремень, носки)": {"size": "23×17×13 см", "delivery_price": 1200},
    "SMALL (пара обуви в коробке)": {"size": "36×26×14 см", "delivery_price": 2000},
    "LARGE (пара обуви и несколько вещей)": {"size": "40×29×16 см", "delivery_price": 2900},
    "XXL (две пары обуви и вещи)": {"size": "37×29×28 см", "delivery_price": 4000},
}

def get_box_keyboard():
    return ReplyKeyboardMarkup([[k] for k in BOX_TYPES.keys()], resize_keyboard=True, one_time_keyboard=True)

def format_price(price: float) -> str:
    return f"{int(price):,} ₽".replace(",", " ")

async def get_cny_rate() -> float:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(CBR_API_URL)
            resp.raise_for_status()
            data = resp.json()
            val = data["Valute"]["CNY"]
            return round(val["Value"] / val["Nominal"], 2)
    except Exception as e:
        logger.error(f"Ошибка получения курса: {e}")
        return 12.5

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "👟 Введите цену товара в юанях (CNY):\nПример: 1500",
        reply_markup=ReplyKeyboardMarkup([["/cancel"]], resize_keyboard=True),
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
    context.user_data.update({"price": price, "cny_rate": cny_rate})

    await update.message.reply_text(
        f"📦 Выберите коробку (курс: 1 CNY = {cny_rate} RUB):",
        reply_markup=get_box_keyboard(),
    )
    return BOX

async def handle_box(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "/cancel":
        return await cancel(update, context)
    if text not in BOX_TYPES:
        await update.message.reply_text("❌ Выберите вариант из списка:", reply_markup=get_box_keyboard())
        return BOX

    box = BOX_TYPES[text]
    price_cny = context.user_data["price"]
    cny_rate = context.user_data["cny_rate"]
    price_rub = price_cny * cny_rate
    delivery_price = box["delivery_price"]
    total = price_rub + delivery_price + SERVICE_FEE

    result = (
        f"📊 *Итоговый расчет*\n\n"
        f"📦 {text}\n"
        f"• Размер: {box['size']}\n"
        f"• Доставка: {format_price(delivery_price)}\n\n"
        f"💵 Товар: {format_price(price_rub)}\n"
        f"(Цена: {price_cny} CNY × Курс: {cny_rate} RUB)\n\n"
        f"💼 Комиссия: {format_price(SERVICE_FEE)}\n"
        f"══════════════════\n"
        f"💳 *Итого: {format_price(total)}*"
    )
    await update.message.reply_text(result, parse_mode="Markdown", reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True))
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "❌ Отменено. Для нового расчета /start", reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True)
    )
    return ConversationHandler.END

if __name__ == "__main__":
    # Инициализация приложения
    application = ApplicationBuilder().token(TOKEN).build()
    
    # Настройка обработчиков
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_price)],
            BOX: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_box)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(conv_handler)
    
    # Конфигурация вебхука
    webhook_path = f"/webhook/{TOKEN}"
    webhook_url = f"{APP_URL}{webhook_path}"
    port = int(os.environ.get("PORT", "8443"))
    
    # Проверка переменных окружения
    if not TOKEN:
        logger.error("Переменная BOT_TOKEN не установлена!")
        exit(1)
    
    if not APP_URL:
        logger.warning("RENDER_EXTERNAL_URL не установлен, используем polling")
        application.run_polling()
    else:
        try:
            # Запуск вебхука
            logger.info(f"Запуск бота на порту {port} с вебхуком {webhook_url}")
            application.run_webhook(
                listen="0.0.0.0",
                port=port,
                url_path=webhook_path,
                webhook_url=webhook_url,
                secret_token=os.getenv("WEBHOOK_SECRET", "your-secret-token"),
                drop_pending_updates=True
            )
        except Exception as e:
            logger.error(f"Ошибка вебхука: {e}, переключаемся на polling")
            application.run_polling()