import http.server
import socketserver
import threading
import requests
import pandas as pd
import time
import os
from telegram.ext import Updater, CommandHandler

# === Configuraciones ===
CMC_API_KEY = os.getenv("CMC_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

EXCLUIR = {"USDT", "DAI", "TUSD", "USDC", "BUSD", "FDUSD"}

# === Funciones de análisis técnico (si las necesitás luego) ===
def obtener_velas_binance(symbol, intervalo="1h", total_velas=5000):
    url = "https://api.binance.com/api/v3/klines"
    velas = []
    limite = 1000
    ms_intervalo = 60 * 60 * 1000
    ahora = int(time.time() * 1000)
    desde = ahora - total_velas * ms_intervalo

    while len(velas) < total_velas:
        params = {
            "symbol": symbol,
            "interval": intervalo,
            "limit": limite,
            "startTime": desde
        }
        r = requests.get(url, params=params)
        data = r.json()
        if not isinstance(data, list) or len(data) == 0:
            return None
        velas.extend(data)
        desde = data[-1][0] + ms_intervalo
        time.sleep(0.2)

    df = pd.DataFrame(velas[:total_velas], columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "number_of_trades",
        "taker_buy_base_volume", "taker_buy_quote_volume", "ignore"
    ])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df

# === Alerta a Telegram ===
def enviar_alerta(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "Markdown"}
    requests.post(url, data=data)

# === Comando /start ===
def start(update, context):
    update.message.reply_text("🤖 ¡Bot de alertas activado correctamente!")

# === Comando /movimientos ===
def movimientos(update, context):
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
    params = {"start": "1", "limit": "200", "convert": "USD"}

    try:
        r = requests.get(url, headers=headers, params=params)
        data = r.json().get("data", [])
    except Exception:
        update.message.reply_text("❌ Error al consultar CoinMarketCap.")
        return

    cambios = []
    for cripto in data:
        symbol = cripto["symbol"]
        if symbol in EXCLUIR:
            continue
        cambio_1h = cripto["quote"]["USD"].get("percent_change_1h", None)
        if cambio_1h is not None:
            cambios.append((symbol, cambio_1h))

    cambios.sort(key=lambda x: x[1], reverse=True)
    top_subas = cambios[:5]
    top_bajas = cambios[-5:]

    mensaje = "📊 *Top 5 que más subieron en 1h:*\n"
    for sym, pct in top_subas:
        mensaje += f"🟢 {sym}: +{pct:.2f}%\n"

    mensaje += "\n📉 *Top 5 que más bajaron en 1h:*\n"
    for sym, pct in top_bajas:
        mensaje += f"🔻 {sym}: {pct:.2f}%\n"

    context.bot.send_message(chat_id=update.effective_chat.id, text=mensaje, parse_mode="Markdown")

# === Keep-alive para Render ===
def keep_alive():
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", 10000), handler) as httpd:
        httpd.serve_forever()

# === Main del bot ===
def main():
    if not TELEGRAM_TOKEN:
        print("❌ No se encontró el token de Telegram.")
        return

    threading.Thread(target=keep_alive).start()

    updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("movimientos", movimientos))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
