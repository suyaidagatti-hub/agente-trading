"""
scanner.py — corre en GitHub Actions cada 6 horas.
No necesita bot de Telegram activo, solo manda mensajes.
"""
import asyncio
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

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
    print(f"Scanner iniciado — {ahora}")

    portfolio = load_portfolio()
    lineas    = portfolio["lineas"]

    # Monedas activas para excluirlas de candidatos
    excluir = [
        lineas[k]["moneda_actual"].replace("USDT", "")
        for k in ["linea_1", "linea_2"]
        if lineas[k]["moneda_actual"] != "USDT"
    ]

    print("Recolectando datos de mercado...")
    market_data = recolectar_datos(portfolio)

    print("Escaneando candidatos trending...")
    candidatos  = escanear_candidatos(excluir=excluir)

    print("Analizando con IA...")
    analisis = analizar_portfolio(portfolio, market_data, candidatos)

    estado_mercado = analisis.get("estado_mercado", "?")
    print(f"Mercado: {estado_mercado}")

    # Detectar si hay alguna señal urgente
    alertas_urgentes = []
    for key in ["linea_1", "linea_2"]:
        a       = analisis.get(key, {})
        accion  = a.get("accion", "MANTENER")
        urgencia = a.get("urgencia", "BAJA")
        num     = "1" if key == "linea_1" else "2"

        if urgencia == "ALTA" and accion in ("VENDER", "COMPRAR", "ROTAR"):
            alertas_urgentes.append(f"Linea {num}: {accion}")

    if alertas_urgentes:
        print(f"Alertas urgentes: {alertas_urgentes}")
        encabezado = f"ALERTA AUTOMATICA\n{', '.join(alertas_urgentes)}\n\n"
        await send_telegram(encabezado + formato_estado(portfolio, analisis, candidatos))
    else:
        print("Sin alertas urgentes en este scan.")
        # Igual mandamos un resumen corto para saber que el agente está vivo
        fear = get_fear_greed()
        mercado = get_mercado_global()
        resumen = (
            f"Scan OK — {ahora}\n"
            f"Mercado: {estado_mercado}\n"
            f"Fear & Greed: {fear['valor_hoy']}/100 ({fear['clasificacion']})\n"
            f"BTC dominancia: {mercado['btc_dominancia']}%\n"
            f"Sin señales urgentes."
        )
        print(resumen)
        # Solo mandamos resumen en el scan de las 8 AM UTC (reporte diario)
        hora_actual = datetime.utcnow().hour
        if hora_actual == 8:
            await send_telegram(
                f"REPORTE DIARIO\n\n{resumen}\n\n" +
                formato_estado(portfolio, analisis, candidatos)
            )


if __name__ == "__main__":
    asyncio.run(main())
