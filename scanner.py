"""
scanner.py — corre en GitHub Actions cada 6 horas.
Las variables de entorno vienen del workflow, no del .env
"""
import os, asyncio
from datetime import datetime

# En GitHub Actions no hay .env, las vars vienen del entorno directamente
# Verificar que están antes de importar agent
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
)


async def main():
    ahora = datetime.utcnow().strftime("%d %b %Y · %H:%M UTC")
    print(f"\nScanner iniciado — {ahora}")

    portfolio = load_portfolio()
    lineas    = portfolio["lineas"]

    excluir = [
        lineas[k]["moneda_actual"].replace("USDT", "")
        for k in ["linea_1", "linea_2"]
        if lineas[k]["moneda_actual"] != "USDT"
    ]

    print("Recolectando datos de posiciones actuales...")
    market_data = recolectar_datos(portfolio)

    print("Escaneando candidatos trending...")
    candidatos  = escanear_candidatos(excluir=excluir)

    print("Analizando con IA...")
    analisis = analizar_portfolio(portfolio, market_data, candidatos)

    estado_mercado = analisis.get("estado_mercado", "?")
    print(f"Resultado — Mercado: {estado_mercado}")

    # Detectar señales urgentes
    alertas = []
    for key in ["linea_1", "linea_2"]:
        a        = analisis.get(key, {})
        accion   = a.get("accion", "MANTENER")
        urgencia = a.get("urgencia", "BAJA")
        num      = "1" if key == "linea_1" else "2"
        print(f"  Linea {num}: {accion} [{urgencia}] — {a.get('razonamiento','')[:80]}")
        if urgencia == "ALTA" and accion in ("VENDER", "COMPRAR", "ROTAR"):
            alertas.append(f"Linea {num}: {accion}")

    if alertas:
        print(f"\nAlertas urgentes detectadas: {alertas}")
        encabezado = f"ALERTA AUTOMATICA\n{', '.join(alertas)}\n\n"
        await send_telegram(encabezado + formato_estado(portfolio, analisis, candidatos))
        print("Alerta enviada por Telegram.")
    else:
        print("\nSin alertas urgentes.")
        # Reporte diario solo a las 8 AM UTC
        hora = datetime.utcnow().hour
        if hora == 8:
            fear    = get_fear_greed()
            mercado = get_mercado_global()
            reporte = (
                f"REPORTE DIARIO — {ahora}\n\n"
                f"Mercado: {estado_mercado}\n"
                f"Fear & Greed: {fear['valor_hoy']}/100 ({fear['clasificacion']})\n"
                f"BTC dominancia: {mercado['btc_dominancia']}%\n\n"
            ) + formato_estado(portfolio, analisis, candidatos)
            await send_telegram(reporte)
            print("Reporte diario enviado.")
        else:
            print(f"(Hora actual: {hora} UTC — reporte diario solo a las 8 UTC)")


if __name__ == "__main__":
    asyncio.run(main())
