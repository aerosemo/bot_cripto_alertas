import os
import asyncio
import logging
import requests
import pandas as pd
import numpy as np
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from datetime import datetime

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

ALERT_INTERVAL = 60 * 14  # 14 minutos
CHECK_INTERVAL = 60 * 5   # cada 5 minutos

BASE_URL = "https://api.bitget.com/api/v2/market/candles"

def get_klines(symbol="BTCUSDT", limit=5000):
    params = {
        "symbol": symbol + "_UMCBL",
        "granularity": "3600",
        "limit": str(limit)
    }
    try:
        r = requests.get(BASE_URL, params=params)
        data = r.json()["data"]
        return data[::-1]  # ordenar cronológicamente
    except Exception as e:
        print(f"Error al obtener velas para {symbol}: {e}")
        return []

def prepare_dataframe(data):
    df = pd.DataFrame(data, columns=[
        "timestamp", "open", "high", "low", "close", "volume", "_"
    ])
    df = df.astype(float)
    df["ema20"] = df["close"].ewm(span=20).mean()
    df["ema50"] = df["close"].ewm(span=50).mean()
    df["ema200"] = df["close"].ewm(span=200).mean()
    return df

def find_levels(df):
    supports, resistances = [], []
    for i in range(2, len(df) - 2):
        if df["low"][i] < df["low"][i - 1] and df["low"][i] < df["low"][i + 1]:
            supports.append(df["low"][i])
        if df["high"][i] > df["high"][i - 1] and df["high"][i] > df["high"][i + 1]:
            resistances.append(df["high"][i])
    return supports, resistances

def get_rejection_signal(df, supports, resistances):
    last = df.iloc[-1]
    prev = df.iloc[-2]
    price = last["close"]
    signal = ""

    for level in supports:
        if abs(price - level) / level < 0.015 and prev["low"] <= level and last["close"] > level and last["volume"] > df["volume"].rolling(20).mean().iloc[-1]:
            signal = f"📉 Rechazo en soporte ${level:.2f} con volumen alto ({last['volume']:.2f})"
            break
    for level in resistances:
        if abs(price - level) / level < 0.015 and prev["high"] >= level and last["close"] < level and last["volume"] > df["volume"].rolling(20).mean().iloc[-1]:
            signal = f"📈 Rechazo en resistencia ${level:.2f} con volumen alto ({last['volume']:.2f})"
            break
    return signal

async def analyze_and_alert():
    symbols = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "ARBUSDT", "VIRTUALUSDT"]
    for symbol in symbols:
        data = get_klines(symbol=symbol)
        if not data:
            continue
        df = prepare_dataframe(data)
        supports, resistances = find_levels(df)
        signal = get_rejection_signal(df, supports, resistances)
        if signal:
            msg = f"🔔 Señal para {symbol}\n{signal}"
            await send_telegram(msg)

async def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text})

async def heartbeat(bot: Bot, chat_id: str):
    while True:
        await bot.send_message(chat_id=chat_id, text="✅ Bot despierto")
        await asyncio.sleep(ALERT_INTERVAL)

async def auto_analyze():
    while True:
        await analyze_and_alert()
        await asyncio.sleep(CHECK_INTERVAL)

async def handle_nivel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Especificá un símbolo. Ej: /nivel BTCUSDT")
        return
    symbol = context.args[0].upper()
    data = get_klines(symbol)
    if not data:
        await update.message.reply_text(f"❌ No se pudo obtener datos de {symbol}")
        return
    df = prepare_dataframe(data)
    supports, resistances = find_levels(df)
    price = df["close"].iloc[-1]

    msg = f"🔍 Niveles para {symbol} (precio actual: ${price:.2f})\n"
    if supports:
        msg += f"📉 Soporte más cercano: ${min(supports, key=lambda x: abs(x - price)):.2f}\n"
    if resistances:
        msg += f"📈 Resistencia más cercana: ${min(resistances, key=lambda x: abs(x - price)):.2f}\n"
    msg += f"📊 EMA50: ${df['ema50'].iloc[-1]:.2f} | EMA200: ${df['ema200'].iloc[-1]:.2f}"
    await update.message.reply_text(msg)

async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("nivel", handle_nivel))
    asyncio.create_task(auto_analyze())
    asyncio.create_task(heartbeat(app.bot, TELEGRAM_CHAT_ID))
    await app.run_polling()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
