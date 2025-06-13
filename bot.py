import os
import time
import logging
import asyncio
import requests
import numpy as np
import pandas as pd
from binance import AsyncClient
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from datetime import datetime

# Configuración inicial
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")

logging.basicConfig(level=logging.INFO)
symbols_data = {}
last_update_time = 0

# Parámetros de análisis
NUM_CANDLES = 5000
TIMEFRAME = "1h"
REJECTION_THRESHOLD = 1.5  # %
ALERT_INTERVAL = 60 * 14  # 14 minutos

# Calcular EMAs
def calculate_emas(df):
    df["EMA20"] = df["close"].ewm(span=20).mean()
    df["EMA50"] = df["close"].ewm(span=50).mean()
    df["EMA100"] = df["close"].ewm(span=100).mean()
    df["EMA200"] = df["close"].ewm(span=200).mean()
    return df

# Detectar soportes y resistencias
def find_levels(df):
    supports, resistances = [], []
    for i in range(2, len(df) - 2):
        if df["low"][i] < df["low"][i-1] and df["low"][i] < df["low"][i+1]:
            supports.append((df["low"][i], i))
        if df["high"][i] > df["high"][i-1] and df["high"][i] > df["high"][i+1]:
            resistances.append((df["high"][i], i))
    return supports, resistances

# Buscar niveles fuertes cercanos
def find_closest_levels(df, supports, resistances, price):
    closest_support = min(supports, key=lambda x: abs(x[0] - price), default=None)
    closest_resistance = min(resistances, key=lambda x: abs(x[0] - price), default=None)
    return closest_support, closest_resistance

def closest_ema_label(df, level_price):
    emas = {
        "EMA20": df["EMA20"].iloc[-1],
        "EMA50": df["EMA50"].iloc[-1],
        "EMA100": df["EMA100"].iloc[-1],
        "EMA200": df["EMA200"].iloc[-1]
    }
    closest = min(emas.items(), key=lambda x: abs(x[1] - level_price))
    return closest[0] if abs(closest[1] - level_price) / level_price < 0.02 else None

# Cargar datos de Binance
async def load_data():
    global symbols_data, last_update_time
    client = await AsyncClient.create(BINANCE_API_KEY, BINANCE_API_SECRET)
    tickers = await client.get_ticker()
    sorted_symbols = sorted([t for t in tickers if t["symbol"].endswith("USDT")],
                            key=lambda x: float(x["quoteVolume"]), reverse=True)[:200]

    for ticker in sorted_symbols:
        symbol = ticker["symbol"]
        klines = await client.get_klines(symbol=symbol, interval=TIMEFRAME, limit=NUM_CANDLES)
        df = pd.DataFrame(klines, columns=["time", "open", "high", "low", "close",
                                           "volume", "_", "_", "_", "_", "_", "_"])
        df["close"] = df["close"].astype(float)
        df["low"] = df["low"].astype(float)
        df["high"] = df["high"].astype(float)
        df["volume"] = df["volume"].astype(float)
        df = calculate_emas(df)
        supports, resistances = find_levels(df)
        symbols_data[symbol] = {"df": df, "supports": supports, "resistances": resistances}
    last_update_time = time.time()
    await client.close_connection()

# Comando /nivel
async def handle_nivel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("⚠️ Tenés que escribir un símbolo, por ejemplo: /nivel BTC")
        return
    symbol = context.args[0].upper()
    if not symbol.endswith("USDT"):
        symbol += "USDT"
    if symbol not in symbols_data:
        await update.message.reply_text(f"❌ No se encontró la moneda {symbol}")
        return
    data = symbols_data[symbol]
    df = data["df"]
    price = df["close"].iloc[-1]
    support, resistance = find_closest_levels(df, data["supports"], data["resistances"], price)
    
    response = f"🔍 Niveles para {symbol} (precio actual ${price:.4f}):\n"

    if support:
        ema_s = closest_ema_label(df, support[0])
        soporte_linea = f"📉 Soporte: ${support[0]:.4f}"
        if ema_s:
            soporte_linea += f" (cerca de {ema_s})"
        response += soporte_linea + "\n"

    if resistance:
        ema_r = closest_ema_label(df, resistance[0])
        resistencia_linea = f"📈 Resistencia: ${resistance[0]:.4f}"
        if ema_r:
            resistencia_linea += f" (cerca de {ema_r})"
        response += resistencia_linea + "\n"

    await update.message.reply_text(response)

# Señal viva cada 14 minutos
async def heartbeat(bot: Bot, chat_id: str):
    while True:
        await bot.send_message(chat_id=chat_id, text="✅ Bot despierto")
        await asyncio.sleep(ALERT_INTERVAL)

# Inicializar bot
async def main():
    await load_data()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("nivel", handle_nivel))
    asyncio.create_task(heartbeat(app.bot, os.getenv("TELEGRAM_CHAT_ID")))
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
