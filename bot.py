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

# === Binance: obtener velas ===
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

# === EMA ===
def calcular_ema(df, periodo=20):
    return df["close"].ewm(span=periodo, adjust=False).mean()

# === Señal de rechazo en zona clave ===
def detectar_rechazo(df):
    if df is None or len(df) < 100:
        return None

    soporte = df["low"].rolling(window=100).min().iloc[-1]
    resistencia = df["high"].rolling(window=100).max().iloc[-1]
    precio_actual = df["close"].iloc[-1]
    volumen_actual = df["volume"].iloc[-1]
    ema = calcular_ema(df).iloc[-1]
    volumen_medio = df["volume"].rolling(window=20).mean().iloc[-1]

    if soporte * 0.995 <= precio_actual <= soporte * 1.005 and precio_actual > df["open"].iloc[-1] and volumen_actual > volumen_medio * 1.5:
        return f"🟢 Rechazo en SOPORTE: {precio_actual:.2f} | Volumen alto | EMA: {ema:.2f}"
    elif resistencia * 0.995 <= precio_actual <= resistencia * 1.005 and precio_actual < df["open"].iloc[-1] and volumen_actual > volumen_medio * 1.5:
        return f"🔴 Rechazo en RESISTENCIA: {precio_actual:.2f} | Volumen alto | EMA: {ema:.2f}"
    return None

# === Señal cuando está cerca de zona clave ===
def detectar_zona_cercana(df):
    if df is None or len(df) < 100:
        return None

    soporte = df["low"].rolling(window=100).min().iloc[-1]
    resistencia = df["high"].rolling(window=100).max().iloc[-1]
    precio_actual = df["close"].iloc[-1]
    ema = calcular_ema(df).iloc[-1]

    if soporte * 1.01 <= precio_actual <= soporte * 1.02:
        return f"🟡 Cerca del SOPORTE: {precio_actual:.2f} | Soporte: {soporte:.2f} | EMA: {ema:.2f}"
    elif resistencia * 0.98 <= precio_actual <= resistencia * 0.99:
        return f"🟡 Cerca de la RESISTENCIA: {precio_actual:.2f} | Resistencia: {resistencia:.2f} | EMA: {ema:.2f}"
    return None

# === Envío de mensajes ===
def enviar_alerta(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "Markdown"}
    requests.post(url, data=data)

# === Ejecutar análisis técnico general ===
def ejecutar_bot():
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
    params = {"start": "1", "limit": "200", "convert": "USD"}

    try:
        r = requests.get(url, headers=headers, params=params)
        data = r.json().get("data", [])
    except Exception as e:
        print("❌ Error al consultar CoinMarketCap:", e)
        return

    for cripto in data:
        symbol = cripto["symbol"]
        if symbol in EXCLUIR:
            continue

        pair = symbol + "USDT"
        df = obtener_velas_binance(pair)
        if df is None:
            continue

        señal = detectar_rechazo(df)
        if señal:
            enviar_alerta(f"{symbol}/USDT - {señal}")
            continue

        zona = detectar_zona_cercana(df)
        if zona:
            enviar_alerta(f"{symbol}/USDT - {zona}")

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

# === Render: mantener puerto abierto ===
def keep_alive():
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", 10000), handler) as httpd:
        httpd.serve_forever()

# === MAIN ===
def main():
    if not TELEGRAM_TOKEN:
        print("❌ No se encontró el token de Telegram.")
        return

    threading.Thread(target=keep_alive).start()

    updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
    dispatcher = updater.dispatcher
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("movimientos", movimientos))

    # Ejecutar escaneo inicial
    ejecutar_bot()

    # Mantener el bot escuchando
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()

