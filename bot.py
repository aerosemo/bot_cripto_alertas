
import asyncio
import logging
import requests
from telegram import Bot
from telegram.ext import ApplicationBuilder, CommandHandler
import os

# Configuración de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Lista de símbolos válidos en Bitget con USDT
SYMBOLS = ["LUMIAUSDT", "GOATUSDT", "GRASSUSDT"]

# Variables de entorno para el bot
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

ALERT_INTERVAL = 60 * 14  # 14 minutos

# Función para obtener velas
async def get_candlesticks(symbol):
    url = f"https://api.bitget.com/api/v2/market/candles?symbol={symbol}&granularity=3600&limit=5000"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return response.json().get("data", [])
        else:
            logger.error(f"Error al obtener velas para {symbol}: {response.status_code} {response.text}")
            return []
    except Exception as e:
        logger.error(f"Excepción al obtener velas para {symbol}: {e}")
        return []

# Función de análisis ficticia por ahora
async def analizar_y_enviar(bot, symbol):
    velas = await get_candlesticks(symbol)
    if not velas:
        return
    logger.info(f"Analizando {symbol} ({len(velas)} velas)")
    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"Análisis técnico iniciado para {symbol}")

# Keepalive
async def heartbeat(bot: Bot, chat_id: str):
    while True:
        await bot.send_message(chat_id=chat_id, text="🤖 Bot operativo (ping de vida)")
        await asyncio.sleep(ALERT_INTERVAL)

# Comando /nivel
async def handle_nivel(update, context):
    await update.message.reply_text("Bot operativo. Analizando mercados en Bitget.")

# Inicializar bot
async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("nivel", handle_nivel))

    bot = app.bot
    asyncio.create_task(heartbeat(bot, TELEGRAM_CHAT_ID))

    while True:
        for symbol in SYMBOLS:
            await analizar_y_enviar(bot, symbol)
            await asyncio.sleep(5)
        await asyncio.sleep(ALERT_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())
