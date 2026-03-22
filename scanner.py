"""
scanner.py — corre en GitHub Actions cada 6 horas.
Las variables de entorno vienen del workflow, no del .env
"""
import os, asyncio
from datetime import datetime

required = ["ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
missing  = [k for k in required if not os.environ.get(k)]
if missing:
    raise EnvironmentError(f"Variables de entorno faltantes: {missing}")

print("Variables de entorno OK")
print(f"ANTHROPIC_API_KEY: {os.environ['ANTHROPIC_API_KEY'][:12]}...")
print(f"TELEGRAM_CHAT_ID:  {os.environ['TELEGRAM_CHAT_ID']}")

from agent import (
    load_portfolio,
    recolectar_datos,
    analizar_portfolio,
    escanear_candidatos,
    formato_estado,
    send_telegram,
    get_fear_greed,
    get_mercado_global,
    base_coin,
)


async def main():
    ahora = datetime.utcnow().strftime("%d %b %Y · %H:%M UTC")
    hora  = datetime.utcnow().hour
    print(f"\nScanner iniciado — {ahora}")

    portfolio = load_portfolio()
    lineas    = portfolio["lineas"]

    excluir = [
        base_coin(lineas[k]["moneda_actual"])
        for k in ["linea_1", "linea_2"]
        if lineas[k]["moneda_actual"] != "USDT"
    ]

    print("Recolectando datos de posiciones actuales...")
    market_data = recolectar_datos(portfolio)

    print("Escaneando candidatos trending...")
    candidatos = escanear_candidatos(excluir=excluir)

    print("Analizando con IA...")
    analisis = analizar_portfolio(portfolio, market_data, candidatos)

    estado_mercado = analisis.get("estado_mercado", "?")
    fear           = get_fear_greed()
    mercado        = get_mercado_global()

    print(f"Resultado — Mercado: {estado_mercado}")

    # ── Clasificar cada línea ──────────────────────────────
    alertas_urgentes = []   # ALTA → alerta inmediata
    updates_posicion = []   # posición abierta → siempre informar

    for key in ["linea_1", "linea_2"]:
        a        = analisis.get(key, {})
        accion   = a.get("accion", "MANTENER")
        urgencia = a.get("urgencia", "BAJA")
        num      = "1" if key == "linea_1" else "2"
        moneda   = lineas[key]["moneda_actual"]
        tiene_posicion = moneda != "USDT"

        print(f"  Linea {num}: {accion} [{urgencia}] — {a.get('razonamiento','')[:80]}")

        # Alerta urgente: acción crítica en cualquier línea
        if urgencia == "ALTA" and accion in ("VENDER", "COMPRAR", "ROTAR"):
            alertas_urgentes.append(f"Linea {num}: {accion}")

        # Update de posición: línea con crypto abierta, siempre informar
        if tiene_posicion:
            pl = round(
                (market_data.get(key, {}).get("technical", {}).get("price", lineas[key]["precio_entrada"])
                 - lineas[key]["precio_entrada"])
                / max(lineas[key]["precio_entrada"], 0.0001) * 100, 2
            )
            signo = "+" if pl >= 0 else ""
            updates_posicion.append(
                f"Linea {num} — {moneda}\n"
                f"P&L: {signo}{pl}%  |  {accion} [{urgencia}]\n"
                f"{a.get('razonamiento','')}"
            )

    # ── Enviar mensajes ────────────────────────────────────

    # 1. Alertas urgentes → siempre, inmediatamente
    if alertas_urgentes:
        print(f"\nAlertas urgentes: {alertas_urgentes}")
        encabezado = f"ALERTA AUTOMATICA\n{', '.join(alertas_urgentes)}\n\n"
        await send_telegram(encabezado + formato_estado(portfolio, analisis, candidatos))
        print("Alerta urgente enviada.")

    # 2. Update de posiciones abiertas → cada scan (cada 6 horas)
    elif updates_posicion:
        msg = (
            f"UPDATE DE POSICIONES\n"
            f"{ahora}\n"
            f"Mercado: {estado_mercado}  |  Fear & Greed: {fear['valor_hoy']}/100\n\n"
        )
        for u in updates_posicion:
            msg += u + "\n\n"

        # Agregar top trending si hay candidatos
        if candidatos:
            msg += "Top trending ahora:\n"
            for c in candidatos[:3]:
                s = "+" if c["change_pct"] >= 0 else ""
                msg += f"  {base_coin(c['symbol'])}: Score {c['score']}/12 | RSI {c['rsi']} | {s}{c['change_pct']:.1f}%\n"

        await send_telegram(msg)
        print("Update de posiciones enviado.")

    # 3. Reporte diario completo → scan de las 6 AM UTC (primer scan de la mañana)
    elif hora == 6:
        reporte = (
            f"REPORTE DIARIO\n"
            f"{ahora}\n\n"
            f"Mercado: {estado_mercado}\n"
            f"Fear & Greed: {fear['valor_hoy']}/100 ({fear['clasificacion']})\n"
            f"Tendencia F&G: {fear['tendencia']}\n"
            f"BTC dominancia: {mercado['btc_dominancia']}%\n"
            f"Cambio mcap 24h: {mercado['cambio_mcap_24h']}%\n\n"
        ) + formato_estado(portfolio, analisis, candidatos)
        await send_telegram(reporte)
        print("Reporte diario enviado.")

    else:
        print(f"Sin alertas urgentes ni posiciones abiertas. Hora: {hora} UTC")
        print("(Reporte diario se envía en el scan de las 6 AM UTC)")


if __name__ == "__main__":
    asyncio.run(main())
