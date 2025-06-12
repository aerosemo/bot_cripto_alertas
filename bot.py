import http.server
import socketserver
import threading
import requests
import pandas as pd
import time
import os
from telegram.ext import Updater, CommandHandler

# Configuraciones
CMC_API_KEY = os.getenv("CMC_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Excluir monedas que no tienen par en Binance o son estables
EXCLUIR = {"USDT", "DAI", "TUSD", "USDC", "BUSD", "FDUSD"}

# Obtener el top 200 desde CoinMarketCap
def obtener_top_200():
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
    params = {"start": "1", "limit": "200", "convert": "USD"}
    r = requests.get(url, headers=headers, params=params)
    response = r.json()
    if "data" not in response:
        print("❌ Error al obtener datos de CoinMarketCap:", response)
        return []
    return [cripto["symbol"] for cripto in response["data"] if cripto["symbol"] not in EXCLUIR]

# Obtener las velas desde Binance
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
        "taker_buy_base_volume", "taker_buy_quote_volume", "ignore"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df

# Calcular EMAs
def calcular_ema(df, periodo):
    return df["close"].ewm(span=periodo, adjust=False).mean()

# Detectar rechazos con volumen
def detectar_rechazo(df):
    if df is None or len(df) < 100:
        return None
    soporte = df["low"].rolling(window=100).min().iloc[-1]
    resistencia = df["high"].rolling(window=100).max().iloc[-1]
    precio_actual = df["close"].iloc[-1]
    volumen_actual = df["volume"].iloc[-1]
    ema = calcular_ema(df, 20).iloc[-1]
    volumen_medio = df["volume"].rolling(window=20).mean().iloc[-1]
    if soporte * 0.995 <= precio_actual <= soporte * 1.005 and precio_actual > df["open"].iloc[-1] and volumen_actual > volumen_medio * 1.5:
        return f"🟢 Rechazo en SOPORTE: {precio_actual:.2f} | Volumen alto | EMA20: {ema:.2f}"
    elif resistencia * 0.995 <= precio_actual <= resistencia * 1.005 and precio_actual < df["open"].iloc[-1] and volumen_actual > volumen_medio * 1.5:
        return f"🔴 Rechazo en RESISTENCIA: {precio_actual:.2f} | Volumen alto | EMA20: {ema:.2f}"
    return None

# Alerta cercanía a soportes/resistencias con EMAs
def detectar_cercania_sr(df):
    if df is None or len(df) < 100:
        return None
    precio_actual = df["close"].iloc[-1]
    soportes = [df["low"].rolling(window=w).min().iloc[-1] for w in [50, 100, 200]]
    resistencias = [df["high"].rolling(window=w).max().iloc[-1] for w in [50, 100, 200]]
    emas = {w: calcular_ema(df, w).iloc[-1] for w in [20, 50, 100, 200]}
    for i, soporte in enumerate(soportes):
        if soporte * 0.99 <= precio_actual <= soporte * 1.01:
            return f"🛠️ Cerca de SOPORTE: {precio_actual:.2f} | EMA relevante: {emas.get([20,50,100,200][i], 0):.2f}"
    for i, resistencia in enumerate(resistencias):
        if resistencia * 0.99 <= precio_actual <= resistencia * 1.01:
            return f"⚡️ Cerca de RESISTENCIA: {precio_actual:.2f} | EMA relevante: {emas.get([20,50,100,200][i], 0):.2f}"
    return None

# Enviar mensaje por Telegram
def enviar_alerta(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje}
    requests.post(url, data=data)

# Comando /start y /movimientos
def start(update, context):
    update.message.reply_text("🤖 ¡Bot de alertas activado correctamente!")

def movimientos(update, context):
    monedas = obtener_top_200()
    cambios = []
    for symbol in monedas:
        df = obtener_velas_binance(symbol + "USDT", total_velas=2)
        if df is None or len(df) < 2:
            continue
        cambio = ((df["close"].iloc[-1] - df["open"].iloc[0]) / df["open"].iloc[0]) * 100
        cambios.append((symbol, cambio))
    mayores = sorted([c for c in cambios if c[1] > 0], key=lambda x: -x[1])[:5]
    menores = sorted([c for c in cambios if c[1] < 0], key=lambda x: x[1])[:5]
    texto = "🎟 Top 5 que más subieron en 1h:\n"
    for m in mayores:
        texto += f"🔵 {m[0]}: +{m[1]:.2f}%\n"
    texto += "\n🔻 Top 5 que más bajaron en 1h:\n"
    for m in menores:
        texto += f"🔻 {m[0]}: {m[1]:.2f}%\n"
    update.message.reply_text(texto)

# Ejecutar bot principal y enviar keep-alive cada 14 minutos
def bucle_principal():
    while True:
        symbols = obtener_top_200()
        for symbol in symbols:
            try:
                df = obtener_velas_binance(symbol + "USDT")
                señal1 = detectar_rechazo(df)
                señal2 = detectar_cercania_sr(df)
                if señal1:
                    enviar_alerta(f"{symbol}/USDT - {señal1}")
                if señal2:
                    enviar_alerta(f"{symbol}/USDT - {señal2}")
            except Exception:
                continue
        enviar_alerta("🔍 Estoy despierto")
        time.sleep(60 * 14)

# Mantener el puerto activo para Render
def keep_alive():
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", 10000), handler) as httpd:
        httpd.serve_forever()

# Main
if __name__ == "__main__":
    threading.Thread(target=keep_alive).start()
    threading.Thread(target=bucle_principal).start()
    updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
    dispatcher = updater.dispatcher
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("movimientos", movimientos))
    updater.start_polling()
    updater.idle()
