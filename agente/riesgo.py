"""Scoring de riesgo y priorización de la cartera.

El puntaje (0-100) combina lo que un analista de cobranzas mira primero:
cuánto hace que está vencido, cuánto debe, cómo pagó históricamente y si
incumplió promesas de pago. Es transparente a propósito: cada factor queda
en su propia columna para poder explicarle al equipo por qué un cliente
está arriba en la lista.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

COLUMNAS = [
    "cliente",
    "contacto",
    "canal",
    "saldo_vencido",
    "dias_atraso",
    "facturas_vencidas",
    "atraso_promedio_hist",
    "promesas_incumplidas",
]

SEGMENTOS = [  # (puntaje mínimo, nombre, estrategia)
    (75, "Crítico", "Escalar: llamada del responsable y propuesta formal; evaluar suspensión de crédito"),
    (50, "Alto", "Seguimiento firme con fecha concreta y opción de plan de pagos"),
    (25, "Medio", "Recordatorio claro con el detalle de lo adeudado y link de pago"),
    (0, "Bajo", "Recordatorio amable, priorizando la relación comercial"),
]

PESOS = {"atraso": 0.40, "monto": 0.25, "historial": 0.20, "promesas": 0.15}


def _escala(serie: pd.Series, tope: float) -> pd.Series:
    return (serie.clip(lower=0) / tope).clip(upper=1.0)


def puntuar(cartera: pd.DataFrame) -> pd.DataFrame:
    faltan = set(COLUMNAS) - set(cartera.columns)
    if faltan:
        raise ValueError(f"A la cartera le faltan columnas: {sorted(faltan)}")
    df = cartera.copy()

    # Cada factor queda normalizado entre 0 y 1
    df["f_atraso"] = _escala(df["dias_atraso"], 120)
    # el monto se compara contra la propia cartera (log para que un gigante no aplaste al resto)
    log_monto = np.log1p(df["saldo_vencido"].clip(lower=0))
    rango = log_monto.max() - log_monto.min()
    df["f_monto"] = (log_monto - log_monto.min()) / rango if rango else 0.5
    df["f_historial"] = _escala(df["atraso_promedio_hist"], 60)
    df["f_promesas"] = _escala(df["promesas_incumplidas"], 3)

    df["puntaje"] = (
        100
        * (
            PESOS["atraso"] * df["f_atraso"]
            + PESOS["monto"] * df["f_monto"]
            + PESOS["historial"] * df["f_historial"]
            + PESOS["promesas"] * df["f_promesas"]
        )
    ).round(0).astype(int)

    df["segmento"] = df["puntaje"].map(segmento_de)
    df["estrategia"] = df["segmento"].map({n: e for _, n, e in SEGMENTOS})
    # prioridad: riesgo ponderado por plata en juego
    df["prioridad"] = (df["puntaje"] * df["saldo_vencido"] / 1_000_000).round(1)
    return df.sort_values(["prioridad", "puntaje"], ascending=False).reset_index(drop=True)


def segmento_de(puntaje: int) -> str:
    for minimo, nombre, _ in SEGMENTOS:
        if puntaje >= minimo:
            return nombre
    return SEGMENTOS[-1][1]


def explicar(fila: pd.Series) -> str:
    """Explicación en una línea de por qué un cliente tiene ese puntaje."""
    motivos = []
    if fila["dias_atraso"] >= 60:
        motivos.append(f"{int(fila['dias_atraso'])} días de atraso")
    elif fila["dias_atraso"] >= 15:
        motivos.append(f"atraso de {int(fila['dias_atraso'])} días")
    if fila["f_monto"] >= 0.7:
        motivos.append("saldo alto para la cartera")
    if fila["atraso_promedio_hist"] >= 30:
        motivos.append("historial de pagos tardíos")
    if fila["promesas_incumplidas"] >= 1:
        n = int(fila["promesas_incumplidas"])
        motivos.append(f"{n} promesa{'s' if n > 1 else ''} incumplida{'s' if n > 1 else ''}")
    return ", ".join(motivos) if motivos else "atraso reciente y buen historial"
