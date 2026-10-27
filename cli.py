"""Genera el plan de cobranza del día.

    python cli.py --demo --top 10
    python cli.py --cartera cartera.csv --salida plan_cobranza.csv
    ANTHROPIC_API_KEY=... python cli.py --demo     # mensajes redactados por Claude
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from agente import Redactor, puntuar
from agente.demo import generar


def main() -> None:
    ap = argparse.ArgumentParser(description="Agente de IA de cobranzas: prioriza la cartera y redacta los mensajes")
    ap.add_argument("--cartera", help="CSV o Excel con la cartera vencida")
    ap.add_argument("--demo", action="store_true", help="Usar la cartera de ejemplo")
    ap.add_argument("--top", type=int, default=10, help="Cuántos clientes gestionar hoy")
    ap.add_argument("--salida", default="plan_cobranza.csv")
    ap.add_argument("--sin-ia", action="store_true", help="Forzar el modo plantillas")
    a = ap.parse_args()

    if a.demo:
        df = generar()
    elif a.cartera:
        p = Path(a.cartera)
        df = pd.read_excel(p) if p.suffix.lower() in {".xlsx", ".xls"} else pd.read_csv(p)
    else:
        ap.error("Indicá --cartera o usá --demo")

    cartera = puntuar(df)
    agente = Redactor(usar_ia=False if a.sin_ia else None)
    plan = agente.plan_del_dia(cartera, top=a.top)
    plan.to_csv(a.salida, index=False)

    print(f"\n  Modo: {'IA (Claude)' if agente.usar_ia else 'plantillas'}  ·  Cartera: {len(cartera)} clientes")
    print(f"  Saldo vencido total: $ {cartera['saldo_vencido'].sum():,.0f}")
    print("  " + "  ·  ".join(f"{s}: {n}" for s, n in cartera["segmento"].value_counts().items()))
    print(f"\n  Top {a.top} de hoy:")
    for i, f in plan.iterrows():
        print(f"   {i + 1:>2}. [{f['segmento']:<7}] {f['cliente']:<30} {f['canal']:<8} → {f['accion']}")
    if agente.errores:
        print(f"\n  {len(agente.errores)} mensajes de IA rechazados por validación (se usó plantilla).")
    print(f"\n  Plan guardado en {a.salida}\n")


if __name__ == "__main__":
    main()
