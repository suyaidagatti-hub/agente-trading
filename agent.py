import os, json, requests
from datetime import datetime
from dotenv import load_dotenv
import numpy as np

load_dotenv()

# Cliente Anthropic inicializado de forma lazy para evitar error en import
_anthropic_client = None

def get_anthropic():
    global _anthropic_client
    if _anthropic_client is None:
        from anthropic import Anthropic
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise ValueError("ANTHROPIC_API_KEY no encontrada en las variables de entorno")
        _anthropic_client = Anthropic(api_key=key)
    return _anthropic_client

BOT_TOKEN    = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID      = os.environ.get("TELEGRAM_CHAT_ID", "")
PORTFOLIO_F  = "portfolio.json"
BASE_BINANCE = "https://api.binance.com"

BLACKLIST = {"USDT","USDC","BUSD","DAI","TUSD","USDP","BTC","ETH","WBTC","STETH"}

# Watchlist de respaldo si CoinGecko falla (actualizada manualmente)
FALLBACK_WATCHLIST = [
    "SOLUSDT","BNBUSDT","AVAXUSDT","DOTUSDT","LINKUSDT",
    "MATICUSDT","ARBUSDT","OPUSDT","INJUSDT","SUIUSDT",
    "APTUSDT","SEIUSDT","TIAUSDT","JUPUSDT","WLDUSDT"
]

_market_cache = {}


# ─────────────────────────────────────────────────────────────
#  PERSISTENCIA
# ─────────────────────────────────────────────────────────────

def load_portfolio():
    with open(PORTFOLIO_F, encoding="utf-8") as f:
        return json.load(f)

def save_portfolio(p):
    p["ultima_actualizacion"] = datetime.utcnow().isoformat()
    with open(PORTFOLIO_F, "w", encoding="utf-8") as f:
        json.dump(p, f, indent=2, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────
#  TRENDING COINS con fallback
# ─────────────────────────────────────────────────────────────

def get_trending_coins(top_n=15):
    symbols = []
    coingecko_ok = False

    # Intentar CoinGecko trending
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/search/trending",
            timeout=10
        )
        if r.status_code == 200:
            for item in r.json().get("coins", []):
                sym = item["item"]["symbol"].upper()
                if sym not in BLACKLIST:
                    symbols.append(sym)
            coingecko_ok = True
            print(f"  CoinGecko trending: {symbols[:8]}")
    except Exception as e:
        print(f"  CoinGecko trending no disponible: {e}")

    # Intentar CoinGecko gainers
    if coingecko_ok:
        try:
            r = requests.get(
                "https://api.coingecko.com/api/v3/coins/markets",
                params={
                    "vs_currency": "usd",
                    "order": "price_change_percentage_24h_desc",
                    "per_page": 20,
                    "page": 1,
                    "price_change_percentage": "24h",
                },
                timeout=10
            )
            if r.status_code == 200:
                for coin in r.json():
                    sym = coin["symbol"].upper()
                    if sym not in BLACKLIST and coin.get("price_change_percentage_24h", 0) > 3:
                        symbols.append(sym)
        except Exception as e:
            print(f"  CoinGecko gainers no disponible: {e}")

    # Si CoinGecko no devolvió nada, usar watchlist de respaldo
    if not symbols:
        print("  Usando watchlist de respaldo...")
        symbols = [s.replace("USDT", "") for s in FALLBACK_WATCHLIST]

    # Deduplicar
    seen, unique = set(), []
    for s in symbols:
        if s not in seen:
            seen.add(s)
            unique.append(s)

    # Verificar disponibilidad en Binance
    validos = []
    for sym in unique[:top_n + 10]:
        pair = sym + "USDT"
        try:
            r = requests.get(
                f"{BASE_BINANCE}/api/v3/ticker/price",
                params={"symbol": pair},
                timeout=5
            )
            if r.status_code == 200:
                validos.append(pair)
                if len(validos) >= top_n:
                    break
        except:
            continue

    print(f"  Coins válidos ({len(validos)}): {[v.replace('USDT','') for v in validos]}")
    return validos


# ─────────────────────────────────────────────────────────────
#  DATOS DE MERCADO
# ─────────────────────────────────────────────────────────────

def get_klines(symbol, interval="4h", limit=100):
    r = requests.get(
        f"{BASE_BINANCE}/api/v3/klines",
        params={"symbol": symbol, "interval": interval, "limit": limit},
        timeout=10
    )
    r.raise_for_status()
    return [
        {"open": float(d[1]), "high": float(d[2]),
         "low": float(d[3]), "close": float(d[4]), "volume": float(d[5])}
        for d in r.json()
    ]

def get_ticker(symbol):
    r = requests.get(
        f"{BASE_BINANCE}/api/v3/ticker/24hr",
        params={"symbol": symbol}, timeout=10
    )
    d = r.json()
    return {
        "change_pct": float(d["priceChangePercent"]),
        "volume_24h": float(d["quoteVolume"]),
        "price":      float(d["lastPrice"]),
    }

def get_lunarcrush(symbol):
    try:
        coin = symbol.replace("USDT", "").lower()
        key  = os.environ.get("LUNARCRUSH_API_KEY", "")
        r = requests.get(
            f"https://lunarcrush.com/api4/public/coins/{coin}/v1",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10
        )
        d = r.json().get("data", {})
        return {
            "galaxy_score":  d.get("galaxy_score", 0),
            "sentiment":     d.get("sentiment", 0),
            "social_volume": d.get("social_volume", 0),
        }
    except:
        return {"galaxy_score": 0, "sentiment": 0, "social_volume": 0}

def get_fear_greed():
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=3", timeout=10)
        data = r.json()["data"]
        return {
            "valor_hoy":     int(data[0]["value"]),
            "clasificacion": data[0]["value_classification"],
            "valor_ayer":    int(data[1]["value"]),
            "tendencia":     "subiendo" if int(data[0]["value"]) > int(data[1]["value"]) else "bajando",
        }
    except:
        return {"valor_hoy": 50, "clasificacion": "Neutral", "tendencia": "desconocida"}

def get_mercado_global():
    try:
        r = requests.get("https://api.coingecko.com/api/v3/global", timeout=10)
        if r.status_code == 200:
            d = r.json()["data"]
            return {
                "btc_dominancia":  round(d["market_cap_percentage"]["btc"], 1),
                "eth_dominancia":  round(d["market_cap_percentage"].get("eth", 0), 1),
                "cambio_mcap_24h": round(d["market_cap_change_percentage_24h_usd"], 2),
            }
    except:
        pass
    # Fallback: obtener desde Binance
    try:
        r = requests.get(
            f"{BASE_BINANCE}/api/v3/ticker/24hr",
            params={"symbol": "BTCUSDT"}, timeout=10
        )
        d = r.json()
        return {
            "btc_dominancia":  0,
            "eth_dominancia":  0,
            "cambio_mcap_24h": round(float(d["priceChangePercent"]), 2),
        }
    except:
        return {"btc_dominancia": 0, "cambio_mcap_24h": 0}

def calc_indicators(klines):
    closes  = np.array([k["close"]  for k in klines])
    highs   = np.array([k["high"]   for k in klines])
    lows    = np.array([k["low"]    for k in klines])
    volumes = np.array([k["volume"] for k in klines])

    def ema(arr, n):
        e, k = np.zeros_like(arr), 2 / (n + 1)
        e[n - 1] = arr[:n].mean()
        for i in range(n, len(arr)):
            e[i] = arr[i] * k + e[i - 1] * (1 - k)
        return e

    def rsi(arr, n=14):
        d  = np.diff(arr)
        g  = np.where(d > 0, d, 0)
        l  = np.where(d < 0, -d, 0)
        ag = np.convolve(g, np.ones(n) / n, "valid")
        al = np.convolve(l, np.ones(n) / n, "valid")
        return float(100 - 100 / (1 + ag[-1] / (al[-1] + 1e-10)))

    atr = float(np.mean(np.maximum.reduce([
        highs[-14:] - lows[-14:],
        np.abs(highs[-14:] - closes[-15:-1]),
        np.abs(lows[-14:]  - closes[-15:-1]),
    ])))

    bb_mid = closes[-20:].mean()
    bb_std = closes[-20:].std()

    return {
        "price":        round(float(closes[-1]), 6),
        "ema_20":       round(float(ema(closes, 20)[-1]), 6),
        "ema_50":       round(float(ema(closes, 50)[-1]), 6),
        "rsi_14":       round(rsi(closes), 1),
        "atr":          round(atr, 6),
        "bb_upper":     round(float(bb_mid + 2 * bb_std), 6),
        "bb_lower":     round(float(bb_mid - 2 * bb_std), 6),
        "vwap":         round(float((closes[-20:] * volumes[-20:]).sum() / volumes[-20:].sum()), 6),
        "volume_ratio": round(float(volumes[-1] / volumes[-20:].mean()), 2),
    }

def full_market_data(symbol):
    try:
        klines = get_klines(symbol)
        return {
            "symbol":     symbol,
            "technical":  calc_indicators(klines),
            "ticker_24h": get_ticker(symbol),
            "lunarcrush": get_lunarcrush(symbol),
        }
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}

def recolectar_datos(portfolio):
    global _market_cache
    data = {}
    for key in ["linea_1", "linea_2"]:
        moneda = portfolio["lineas"][key]["moneda_actual"]
        if moneda != "USDT":
            sym = moneda if moneda.endswith("USDT") else moneda + "USDT"
            data[key] = full_market_data(sym)
        else:
            data[key] = {"symbol": "USDT", "technical": {"price": 1.0}, "en_usdt": True}
    _market_cache = data
    return data


# ─────────────────────────────────────────────────────────────
#  ESCANEAR CANDIDATOS
# ─────────────────────────────────────────────────────────────

def escanear_candidatos(excluir=[]):
    print("  Escaneando candidatos...")
    trending = get_trending_coins(top_n=15)

    candidatos = []
    for symbol in trending:
        base = symbol.replace("USDT", "")
        if base in excluir:
            continue
        try:
            data = full_market_data(symbol)
            if "error" in data:
                continue
            t   = data["technical"]
            lc  = data["lunarcrush"]
            tkr = data["ticker_24h"]

            score = 0
            if 35 < t["rsi_14"] < 65:        score += 3
            if t["ema_20"] > t["ema_50"]:     score += 2
            if t["volume_ratio"] > 1.2:       score += 2
            if lc["galaxy_score"] > 50:       score += 2
            if lc["sentiment"] > 3:           score += 1
            if tkr["change_pct"] > 2:         score += 1
            if t["price"] > t["vwap"]:        score += 1

            candidatos.append({
                "symbol":       symbol,
                "score":        score,
                "price":        t["price"],
                "rsi":          t["rsi_14"],
                "change_pct":   round(tkr["change_pct"], 2),
                "galaxy_score": lc["galaxy_score"],
                "volume_ratio": t["volume_ratio"],
                "ema_trend":    "alcista" if t["ema_20"] > t["ema_50"] else "bajista",
            })
        except Exception as e:
            print(f"    Skip {symbol}: {e}")

    candidatos.sort(key=lambda x: x["score"], reverse=True)
    top = candidatos[:5]
    print(f"  Top 5: {[c['symbol'] for c in top]}")
    return top


# ─────────────────────────────────────────────────────────────
#  CEREBRO IA
# ─────────────────────────────────────────────────────────────

SYSTEM = """Sos un gestor de portfolio de crypto conservador-agresivo.
Gestionás 2 líneas de inversión independientes. Objetivo: 50-100% mensual.
Solo operás altcoins trending — NUNCA sugerís BTC ni ETH como destino.

Recibís por cada línea:
- Posición actual, precio de entrada, P&L%
- Indicadores: EMA20/50, RSI14, Bollinger, VWAP, volumen relativo
- Sentimiento: LunarCrush Galaxy Score
- Contexto global: Fear & Greed, dominancia BTC, cambio mcap 24h
- Candidatos trending pre-rankeados con score 0-12

CUÁNDO VENDER:
- RSI > 78 con volumen cayendo
- P&L supera +25% → tomar ganancias
- Precio toca BB superior + Galaxy Score cayendo
- Fear & Greed > 80
- Stop loss: pérdida > 8%
- BTC cae > 5% en 24h → mover a USDT

CUÁNDO COMPRAR:
- Elegir del top de candidatos_trending (score más alto)
- RSI entre 38-62 + EMA 20 sobre EMA 50
- Volume ratio > 1.2 + Fear & Greed entre 20-68
- Nunca las 2 líneas en la misma moneda

NIVELES:
- Stop loss: -8% del precio de entrada
- Take profit 1: +25%
- Take profit 2: +40%

Respondé SOLO JSON sin texto extra:
{
  "linea_1": {
    "accion": "MANTENER|VENDER|COMPRAR|ROTAR",
    "moneda_destino": "par USDT o null",
    "urgencia": "ALTA|MEDIA|BAJA",
    "razonamiento": "max 200 chars",
    "sl_precio": null,
    "tp1_precio": null,
    "tp2_precio": null,
    "confianza": 0
  },
  "linea_2": {
    "accion": "MANTENER|VENDER|COMPRAR|ROTAR",
    "moneda_destino": "par USDT o null",
    "urgencia": "ALTA|MEDIA|BAJA",
    "razonamiento": "max 200 chars",
    "sl_precio": null,
    "tp1_precio": null,
    "tp2_precio": null,
    "confianza": 0
  },
  "estado_mercado": "ALCISTA|NEUTRAL|BAJISTA",
  "resumen": "max 150 chars"
}"""

def analizar_portfolio(portfolio, market_data, candidatos=None):
    lineas = portfolio["lineas"]
    fear_greed = get_fear_greed()
    mercado    = get_mercado_global()

    monedas_activas = [
        lineas[k]["moneda_actual"].replace("USDT", "")
        for k in ["linea_1", "linea_2"]
        if lineas[k]["moneda_actual"] != "USDT"
    ]

    if candidatos is None:
        candidatos = escanear_candidatos(excluir=monedas_activas)

    def pl_pct(key):
        entrada = lineas[key]["precio_entrada"]
        if lineas[key]["moneda_actual"] == "USDT" or entrada == 0:
            return 0
        precio_actual = market_data.get(key, {}).get("technical", {}).get("price", 0)
        return round((precio_actual - entrada) / entrada * 100, 2)

    payload = {
        "contexto_global": {
            "fear_greed":     fear_greed,
            "mercado_global": mercado,
        },
        "candidatos_trending": candidatos,
        "linea_1": {
            "moneda_actual":  lineas["linea_1"]["moneda_actual"],
            "precio_entrada": lineas["linea_1"]["precio_entrada"],
            "capital_usd":    lineas["linea_1"]["capital_usd"],
            "pl_pct":         pl_pct("linea_1"),
            "market_data":    market_data.get("linea_1", {}),
        },
        "linea_2": {
            "moneda_actual":  lineas["linea_2"]["moneda_actual"],
            "precio_entrada": lineas["linea_2"]["precio_entrada"],
            "capital_usd":    lineas["linea_2"]["capital_usd"],
            "pl_pct":         pl_pct("linea_2"),
            "market_data":    market_data.get("linea_2", {}),
        },
    }

    msg = get_anthropic().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=700,
        system=SYSTEM,
        messages=[{"role": "user", "content": json.dumps(payload)}]
    )

    texto = msg.content[0].text.strip()
    inicio = texto.find("{")
    fin    = texto.rfind("}") + 1
    if inicio == -1 or fin == 0:
        raise ValueError(f"JSON no encontrado: {texto[:200]}")
    return json.loads(texto[inicio:fin])


# ─────────────────────────────────────────────────────────────
#  FORMATO Y ENVIO
# ─────────────────────────────────────────────────────────────

def formato_estado(portfolio, analisis, candidatos=None):
    lineas = portfolio["lineas"]
    ts = datetime.utcnow().strftime("%d %b · %H:%M UTC")
    mercado_icon = {"ALCISTA": "↑", "NEUTRAL": "→", "BAJISTA": "↓"}.get(
        analisis.get("estado_mercado", ""), "?")

    def bloque(key, num):
        l = lineas[key]
        a = analisis.get(key, {})
        accion_icon = {
            "MANTENER": "[ = ]", "VENDER": "[ VENDER ]",
            "COMPRAR":  "[ COMPRAR ]", "ROTAR": "[ ROTAR ]",
        }.get(a.get("accion", ""), "[-]")

        texto = (
            f"\n-- Linea {num} --\n"
            f"Posicion: {l['moneda_actual']}  |  Capital: ${l['capital_usd']:.2f}\n"
        )
        if l["moneda_actual"] != "USDT" and l["precio_entrada"] > 0:
            precio_actual = _market_cache.get(key, {}).get("technical", {}).get("price", l["precio_entrada"])
            pl = round((precio_actual - l["precio_entrada"]) / l["precio_entrada"] * 100, 2)
            signo = "+" if pl >= 0 else ""
            texto += f"Entrada: ${l['precio_entrada']}  |  P&L: {signo}{pl:.1f}%\n"

        texto += f"Accion: {accion_icon}  [{a.get('urgencia', '-')}]\n{a.get('razonamiento', '')}\n"

        if a.get("tp1_precio"):
            texto += f"TP1: ${a['tp1_precio']}  TP2: ${a.get('tp2_precio','?')}  SL: ${a.get('sl_precio','?')}\n"
        if a.get("moneda_destino") and a["moneda_destino"] not in (None, "null"):
            texto += f"Destino: {a['moneda_destino']}\n"
        return texto

    resultado = (
        f"REPORTE DE PORTFOLIO\n"
        f"{ts}  |  Mercado: {mercado_icon} {analisis.get('estado_mercado','?')}\n\n"
        f"{analisis.get('resumen', '')}\n"
        f"{bloque('linea_1', 1)}"
        f"{bloque('linea_2', 2)}"
    )

    if candidatos:
        resultado += "\n-- Top Trending --\n"
        for c in candidatos[:3]:
            s = "+" if c["change_pct"] >= 0 else ""
            resultado += (
                f"{c['symbol'].replace('USDT','')}: "
                f"RSI {c['rsi']} | Score {c['score']}/12 | {s}{c['change_pct']:.1f}% 24h\n"
            )

    return resultado

async def send_telegram(text):
    from telegram import Bot
    bot = Bot(token=BOT_TOKEN)
    await bot.send_message(chat_id=CHAT_ID, text=text)


# ─────────────────────────────────────────────────────────────
#  COMANDOS DEL BOT (solo se usan cuando corres agent.py local)
# ─────────────────────────────────────────────────────────────

def main():
    from telegram import Update
    from telegram.ext import Application, CommandHandler, ContextTypes

    async def cmd_estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Analizando, un momento...")
        try:
            portfolio  = load_portfolio()
            mdata      = recolectar_datos(portfolio)
            excluir    = [
                portfolio["lineas"][k]["moneda_actual"].replace("USDT","")
                for k in ["linea_1","linea_2"]
                if portfolio["lineas"][k]["moneda_actual"] != "USDT"
            ]
            candidatos = escanear_candidatos(excluir=excluir)
            analisis   = analizar_portfolio(portfolio, mdata, candidatos)
            await update.message.reply_text(formato_estado(portfolio, analisis, candidatos))
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    async def cmd_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
        p = load_portfolio()
        l = p["lineas"]
        msg = (
            f"PORTFOLIO ACTUAL\n\n"
            f"Linea 1: {l['linea_1']['moneda_actual']}\n"
            f"  Capital: ${l['linea_1']['capital_usd']:.2f}\n"
            f"  Entrada: ${l['linea_1']['precio_entrada']}\n"
            f"  Fecha: {l['linea_1']['fecha_entrada'] or 'sin posicion'}\n\n"
            f"Linea 2: {l['linea_2']['moneda_actual']}\n"
            f"  Capital: ${l['linea_2']['capital_usd']:.2f}\n"
            f"  Entrada: ${l['linea_2']['precio_entrada']}\n"
            f"  Fecha: {l['linea_2']['fecha_entrada'] or 'sin posicion'}\n\n"
            f"Actualizado: {p['ultima_actualizacion'] or 'nunca'}"
        )
        await update.message.reply_text(msg)

    async def cmd_trending(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Buscando trending coins...")
        try:
            candidatos = escanear_candidatos()
            msg = "TOP TRENDING AHORA\n\n"
            for i, c in enumerate(candidatos, 1):
                s = "+" if c["change_pct"] >= 0 else ""
                msg += (
                    f"{i}. {c['symbol'].replace('USDT','')}\n"
                    f"   Score: {c['score']}/12  RSI: {c['rsi']}\n"
                    f"   24h: {s}{c['change_pct']:.1f}%  Vol: x{c['volume_ratio']}\n"
                    f"   Galaxy: {c['galaxy_score']}  Tend: {c['ema_trend']}\n\n"
                )
            await update.message.reply_text(msg)
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    async def cmd_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "COMANDOS\n\n"
            "/estado    — analisis completo + trending\n"
            "/portfolio — ver posiciones actuales\n"
            "/trending  — top monedas del momento\n"
            "/ayuda     — esta ayuda\n\n"
            "Alertas automaticas cada 6h via GitHub Actions."
        )

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("estado",    cmd_estado))
    app.add_handler(CommandHandler("portfolio", cmd_portfolio))
    app.add_handler(CommandHandler("trending",  cmd_trending))
    app.add_handler(CommandHandler("ayuda",     cmd_ayuda))
    app.add_handler(CommandHandler("help",      cmd_ayuda))
    print("Bot corriendo. Comandos: /estado /portfolio /trending /ayuda")
    app.run_polling()

if __name__ == "__main__":
    main()
