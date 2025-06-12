import requests
import pandas as pd
import time

# Configuraciones
CMC_API_KEY = "049e888d-6afd-4626-8925-4971b565ff28"
import os

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Excluir monedas que no tienen par en Binance o son estables
EXCLUIR = {"USDT", "DAI", "TUSD", "USDC", "BUSD", "FDUSD"}

def obtener_top_200():
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
    params = {"start": "1", "limit": "200", "convert": "USDT"}
    r = requests.get(url, headers=headers, params=params)
    data = r.json()["data"]
    return [cripto['symbol'] for cripto in data if cripto['symbol'] not in EXCLUIR]

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

def calcular_ema(df, periodo=20):
    return df["close"].ewm(span=periodo, adjust=False).mean()

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

def enviar_alerta(mensaje):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje}
    requests.post(url, data=data)

def ejecutar_bot():
    symbols = obtener_top_200()
    for symbol in symbols:
        pair = symbol + "USDT"
        try:
            df = obtener_velas_binance(pair)
            señal = detectar_rechazo(df)
            if señal:
                enviar_alerta(f"{symbol}/USDT - {señal}")
        except Exception:
            continue  # Silenciar cualquier error y seguir con la siguiente

ejecutar_bot()
