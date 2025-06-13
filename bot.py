import os
import asyncio
import logging
import requests
from flask import Flask, request
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
import pandas as pd
import numpy as np

# Configuración inicial
TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
flask_app = Flask(__name__)
loop = asyncio.get_event_loop()

logging.basicConfig(level=logging.INFO)

# Comando /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Bot cripto activo. Enviaré señales técnicas y movimientos del mercado.")

# Crear instancia del bot
application = ApplicationBuilder().token(TOKEN).build()

# Registrar comando
application.add_handler(CommandHandler("start", start))

# Iniciar el bot con webhook
loop.run_until_complete(application.initialize())
loop.run_until_complete(application.start())



# Obtener las 200 monedas más activas en Binance por volumen
def obtener_top_monedas():
    try:
        res = requests.get("https://api.binance.com/api/v3/ticker/24hr", timeout=10).json()
        res = sorted([s for s in res if s["symbol"].endswith("USDT")], key=lambda x: float(x["quoteVolume"]), reverse=True)
        return [s["symbol"] for s in res[:200]]
    except Exception as e:
        logging.error(f"Error obteniendo top monedas: {e}")
        return []

# Calcular EMA
def calcular_ema(data, periodo):
    return pd.Series(data).ewm(span=periodo, adjust=False).mean()

# Analizar una cripto
def analizar_moneda(symbol):
    try:
        url = "https://api.binance.com/api/v3/klines"
        r = requests.get(url, params={"symbol": symbol, "interval": "1h", "limit": 500}, timeout=10).json()
        df = pd.DataFrame(r, columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "close_time", "qav", "trades", "tbbav", "tbqav", "ignore"
        ])
        df["close"] = df["close"].astype(float)
        df["low"] = df["low"].astype(float)
        df["high"] = df["high"].astype(float)
        df["volume"] = df["volume"].astype(float)
        df["EMA50"] = calcular_ema(df["close"], 50)
        df["EMA200"] = calcular_ema(df["close"], 200)

        # Soportes / resistencias
        soportes, resistencias = [], []
        for i in range(2, len(df)-2):
            if df["low"][i] < df["low"][i-1] and df["low"][i] < df["low"][i+1] and df["low"][i-1] < df["low"][i-2] and df["low"][i+1] < df["low"][i+2]:
                soportes.append((i, df["low"][i]))
            if df["high"][i] > df["high"][i-1] and df["high"][i] > df["high"][i+1] and df["high"][i-1] > df["high"][i-2] and df["high"][i+1] > df["high"][i+2]:
                resistencias.append((i, df["high"][i]))

        def zonas_clave(niveles):
            zonas = []
            for i in niveles:
                if not any(abs(i[1]-z[1])/z[1] < 0.015 for z in zonas):
                    zonas.append(i)
            return zonas

        zonas_s = zonas_clave(soportes)
        zonas_r = zonas_clave(resistencias)

        precio = df["close"].iloc[-1]
        vol_actual = df["volume"].iloc[-1]
        vol_prom = df["volume"].rolling(20).mean().iloc[-1]

        ema = ""
        if abs(precio - df["EMA50"].iloc[-1])/precio < 0.01:
            ema = "EMA 50"
        elif abs(precio - df["EMA200"].iloc[-1])/precio < 0.01:
            ema = "EMA 200"

        # Rechazo técnico
        for _, zona in zonas_s + zonas_r:
            tipo = "soporte" if (_ , zona) in zonas_s else "resistencia"
            if abs(precio - zona)/zona < 0.005 and vol_actual > 1.5 * vol_prom:
                return f"🔔 Rechazo en zona de {tipo.upper()} para {symbol} con alto volumen ({ema})"

        # Acercamiento
        for _, zona in zonas_s + zonas_r:
            tipo = "soporte" if (_ , zona) in zonas_s else "resistencia"
            if 0.005 < abs(precio - zona)/zona < 0.015:
                return f"⚠️ {symbol} se acerca a zona de {tipo.upper()} (a menos de 1.5%)"

        return None

    except Exception as e:
        logging.error(f"Error en {symbol}: {e}")
        return None

# Análisis periódico de señales
async def analizar_todo():
    while True:
        symbols = obtener_top_monedas()
        for symbol in symbols:
            senal = analizar_moneda(symbol)
            if senal:
                try:
                    await application.bot.send_message(chat_id=CHAT_ID, text=senal)
                except Exception as e:
                    logging.error(f"Error enviando señal: {e}")
        await asyncio.sleep(300)

# Top movimientos en la última hora
def top_movimientos():
    try:
        res = requests.get("https://api.binance.com/api/v3/ticker", timeout=10).json()
        ultimos = {r["symbol"]: float(r["price"]) for r in res if r["symbol"].endswith("USDT")}

        variaciones = []
        for symbol in obtener_top_monedas():
            r = requests.get("https://api.binance.com/api/v3/klines", params={"symbol": symbol, "interval": "1h", "limit": 2}, timeout=10).json()
            if len(r) < 2:
                continue
            open_ = float(r[0][1])
            close = float(r[1][4])
            cambio = ((close - open_) / open_) * 100
            variaciones.append((symbol, cambio))

        top_up = sorted(variaciones, key=lambda x: x[1], reverse=True)[:5]
        top_down = sorted(variaciones, key=lambda x: x[1])[:5]

        texto = "📊 *Movimientos en la última hora:*\n\n🔼 *Subidas:*\n"
        for s, c in top_up:
            texto += f"{s}: +{c:.2f}%\n"
        texto += "\n🔽 *Bajadas:*\n"
        for s, c in top_down:
            texto += f"{s}: {c:.2f}%\n"

        return texto
    except Exception as e:
        logging.error(f"Error en top movimientos: {e}")
        return "📊 No se pudieron calcular los movimientos."

# Keep-alive cada 14 minutos
async def keep_alive():
    while True:
        await asyncio.sleep(840)
        try:
            resumen = top_movimientos()
            await application.bot.send_message(chat_id=CHAT_ID, text=f"✅ Bot activo... esperando señales técnicas.\n\n{resumen}", parse_mode="Markdown")
        except Exception as e:
            logging.error(f"Error en keep-alive: {e}")

# Webhook de Telegram
@flask_app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    json_update = request.get_json(force=True)
    update = Update.de_json(json_update, application.bot)
    loop.create_task(application.process_update(update))
    return "OK"


# Iniciar el bot (webhook y tareas)
loop.run_until_complete(application.initialize())

# Configurar el webhook inmediatamente
webhook_url = f"https://{os.environ['RENDER_EXTERNAL_HOSTNAME']}/{TOKEN}"
loop.run_until_complete(application.bot.set_webhook(webhook_url))

# Lanzar tareas del bot
loop.create_task(analizar_todo())
loop.create_task(keep_alive())


# Servidor Flask
if __name__ == "__main__":
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
