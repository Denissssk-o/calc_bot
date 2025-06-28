import logging
import requests
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = "8156633539:AAGXlHOFkDWztI_Fv6OXd6N2ql5vflnlbb4"

# Константы
SERVICE_FEE = 2000  # Фиксированная комиссия сервиса
CBR_API_URL = "https://www.cbr-xml-daily.ru/daily_json.js"

# Состояния диалога
PRICE, BOX = range(2)

# Коробки с оригинальными названиями и новыми ценами доставки
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
    """Форматирование цены с разделителями"""
    return f"{int(price):,} ₽".replace(",", " ")

async def get_cny_rate() -> float:
    """Получение точного курса юаня от ЦБ РФ"""
    try:
        response = requests.get(CBR_API_URL, timeout=5)
        response.raise_for_status()
        data = response.json()
        cny_rate = data['Valute']['CNY']['Value'] / data['Valute']['CNY']['Nominal']
        return round(cny_rate, 2)
    except Exception as e:
        logger.error(f"Ошибка получения курса: {e}")
        return 12.5  # Резервный курс

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало диалога"""
    try:
        context.user_data.clear()
        await update.message.reply_text(
            "👟 Введите цену товара в юанях (CNY):\n"
            "Пример: 1500",
            reply_markup=ReplyKeyboardMarkup([["/cancel"]], resize_keyboard=True)
        )
        return PRICE
    except Exception as e:
        logger.error(f"Ошибка в start: {e}")
        await update.message.reply_text("❌ Ошибка! Попробуйте /start")
        return ConversationHandler.END

async def handle_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка ввода цены"""
    try:
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
            
        # Получаем курс
        cny_rate = await get_cny_rate()
        context.user_data.update({
            'price': price,
            'cny_rate': cny_rate
        })
        
        await update.message.reply_text(
            f"📦 Выберите коробку (курс: 1 CNY = {cny_rate} RUB):",
            reply_markup=get_box_keyboard()
        )
        return BOX
        
    except Exception as e:
        logger.error(f"Ошибка в handle_price: {e}")
        await update.message.reply_text("❌ Ошибка! Попробуйте /start")
        return ConversationHandler.END

async def handle_box(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора коробки"""
    try:
        text = update.message.text.strip()
        
        if text == "/cancel":
            return await cancel(update, context)
            
        if text not in BOX_TYPES:
            await update.message.reply_text(
                "❌ Выберите вариант из списка:",
                reply_markup=get_box_keyboard()
            )
            return BOX
            
        # Получаем данные
        box_data = BOX_TYPES[text]
        price_cny = context.user_data['price']
        cny_rate = context.user_data['cny_rate']
        
        # Расчет
        price_rub = price_cny * cny_rate
        delivery_price = box_data['delivery_price']
        total = price_rub + delivery_price + SERVICE_FEE
        
        # Формируем ответ
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
        
    except Exception as e:
        logger.error(f"Ошибка в handle_box: {e}")
        await update.message.reply_text("❌ Ошибка расчета! /start")
        return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка отмены"""
    await update.message.reply_text(
        "❌ Отменено. Для нового расчета /start",
        reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True)
    )
    return ConversationHandler.END

def main():
    app = Application.builder().token(TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_price)],
            BOX: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_box)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('cancel', cancel))
    
    logger.info("Бот запущен!")
    app.run_polling()

if __name__ == '__main__':
    main()