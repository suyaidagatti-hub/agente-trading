"""
monitor.py — corre cada 30 minutos via GitHub Actions.
Solo monitorea posiciones abiertas. No escanea el mercado completo.
Sin costo de IA — solo precios de KuCoin y lógica simple.
"""
import os, asyncio, requests
from datetime import datetime

required = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
missing  = [k for k in required if not os.environ.get(k)]
if missing:
    raise EnvironmentError(f"Variables de entorno faltantes: {missing}")

from agent import load_portfolio, send_telegram, get_price, base_coin, to_kucoin

# Umbrales de alerta
SL_ALERTA_PCT   = 3.0   # avisa cuando el precio está a menos del 3% del stop loss
TP_ALERTA_PCT   = 0.5   # avisa cuando el precio está a menos del 0.5% del take profit
CAIDA_HORA_PCT  = 5.0   # avisa si el precio cayó más del 5% en el último chequeo
STOP_LOSS_PCT   = 8.0   # stop loss configurado en el sistema
TP1_PCT         = 25.0  # take profit 1
TP2_PCT         = 40.0  # take profit 2


def calcular_niveles(precio_entrada):
    return {
        "sl":  round(precio_entrada * (1 - STOP_LOSS_PCT / 100), 4),
        "tp1": round(precio_entrada * (1 + TP1_PCT / 100), 4),
        "tp2": round(precio_entrada * (1 + TP2_PCT / 100), 4),
    }

def pct_cambio(precio_actual, referencia):
    if referencia == 0:
        return 0
    return round((precio_actual - referencia) / referencia * 100, 2)


async def main():
    ahora = datetime.utcnow().strftime("%d %b %Y · %H:%M UTC")
    print(f"Monitor iniciado — {ahora}")

    portfolio = load_portfolio()
    lineas    = portfolio["lineas"]
    alertas   = []

    for key in ["linea_1", "linea_2"]:
        l      = lineas[key]
        moneda = l["moneda_actual"]
        num    = "1" if key == "linea_1" else "2"

        # Solo monitorear líneas con posición abierta
        if moneda == "USDT" or l["precio_entrada"] == 0:
            print(f"  Linea {num}: en USDT, sin posicion abierta")
            continue

        entrada = l["precio_entrada"]
        niveles = calcular_niveles(entrada)
        symbol  = to_kucoin(moneda)

        # Obtener precio actual
        try:
            precio_actual = get_price(symbol)
            if precio_actual == 0:
                print(f"  Linea {num}: no se pudo obtener precio de {symbol}")
                continue
        except Exception as e:
            print(f"  Linea {num}: error obteniendo precio — {e}")
            continue

        pl_pct          = pct_cambio(precio_actual, entrada)
        dist_sl_pct     = pct_cambio(precio_actual, niveles["sl"])
        dist_tp1_pct    = pct_cambio(niveles["tp1"], precio_actual)
        signo           = "+" if pl_pct >= 0 else ""

        print(f"  Linea {num} — {base_coin(moneda)}: "
              f"${precio_actual} | P&L: {signo}{pl_pct}% | "
              f"SL: ${niveles['sl']} ({dist_sl_pct:.1f}% lejos) | "
              f"TP1: ${niveles['tp1']} ({dist_tp1_pct:.1f}% lejos)")

        # ── Alerta 1: Stop Loss ejecutado ──────────────────
        if precio_actual <= niveles["sl"]:
            alertas.append({
                "tipo":    "STOP LOSS EJECUTADO",
                "num":     num,
                "moneda":  base_coin(moneda),
                "precio":  precio_actual,
                "pl_pct":  pl_pct,
                "mensaje": (
                    f"STOP LOSS EJECUTADO\n"
                    f"Linea {num} — {base_coin(moneda)}\n"
                    f"Precio: ${precio_actual}  |  P&L: {signo}{pl_pct}%\n\n"
                    f"Vende en tu exchange si no lo hizo automaticamente.\n"
                    f"Registra con: /vender {num} {precio_actual}"
                )
            })

        # ── Alerta 2: Cerca del Stop Loss ──────────────────
        elif dist_sl_pct <= SL_ALERTA_PCT:
            alertas.append({
                "tipo":    "CERCA DEL STOP LOSS",
                "num":     num,
                "moneda":  base_coin(moneda),
                "precio":  precio_actual,
                "pl_pct":  pl_pct,
                "mensaje": (
                    f"ATENCION — Cerca del Stop Loss\n"
                    f"Linea {num} — {base_coin(moneda)}\n"
                    f"Precio actual: ${precio_actual}\n"
                    f"Stop Loss:     ${niveles['sl']}\n"
                    f"Distancia:     {dist_sl_pct:.1f}%\n"
                    f"P&L actual:    {signo}{pl_pct}%\n\n"
                    f"Si no queres esperar al SL, podes vender ahora:\n"
                    f"/vender {num} {precio_actual}"
                )
            })

        # ── Alerta 3: Take Profit 1 alcanzado ─────────────
        elif precio_actual >= niveles["tp1"]:
            alertas.append({
                "tipo":    "TAKE PROFIT 1 ALCANZADO",
                "num":     num,
                "moneda":  base_coin(moneda),
                "precio":  precio_actual,
                "pl_pct":  pl_pct,
                "mensaje": (
                    f"TAKE PROFIT 1 ALCANZADO\n"
                    f"Linea {num} — {base_coin(moneda)}\n"
                    f"Precio actual: ${precio_actual}\n"
                    f"TP1:           ${niveles['tp1']}  (+{TP1_PCT}%)\n"
                    f"TP2:           ${niveles['tp2']}  (+{TP2_PCT}%)\n"
                    f"P&L actual:    +{pl_pct}%\n\n"
                    f"Podes tomar ganancias parciales ahora o esperar el TP2.\n"
                    f"Para registrar venta: /vender {num} {precio_actual}"
                )
            })

        # ── Alerta 4: Cerca del Take Profit 1 ─────────────
        elif dist_tp1_pct <= SL_ALERTA_PCT:
            alertas.append({
                "tipo":    "CERCA DEL TAKE PROFIT",
                "num":     num,
                "moneda":  base_coin(moneda),
                "precio":  precio_actual,
                "pl_pct":  pl_pct,
                "mensaje": (
                    f"Cerca del Take Profit 1\n"
                    f"Linea {num} — {base_coin(moneda)}\n"
                    f"Precio actual: ${precio_actual}\n"
                    f"TP1:           ${niveles['tp1']}\n"
                    f"Faltan:        {dist_tp1_pct:.1f}%\n"
                    f"P&L actual:    +{pl_pct}%"
                )
            })

        # ── Sin alertas: log silencioso ────────────────────
        else:
            print(f"    Sin alertas para Linea {num}. Todo normal.")

    # ── Enviar alertas ─────────────────────────────────────
    if alertas:
        for a in alertas:
            print(f"\n  ALERTA: {a['tipo']} — Linea {a['num']}")
            await send_telegram(a["mensaje"])
        print(f"\n{len(alertas)} alerta(s) enviada(s).")
    else:
        print(f"\nMonitor OK — sin alertas. {ahora}")


if __name__ == "__main__":
    asyncio.run(main())
