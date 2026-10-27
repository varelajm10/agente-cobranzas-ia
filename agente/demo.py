"""Cartera de ejemplo 100% inventada para probar el agente."""

from __future__ import annotations

import random

import pandas as pd

EMPRESAS = [
    "Distribuidora del Sur S.A.", "Constructora Andes S.R.L.", "Ferretería El Tornillo", "Lácteos La Pradera S.A.",
    "Agro Pampa SAS", "Supermercados Norte S.A.", "Logística Rápida S.R.L.", "Panadería San Martín",
    "Maquinarias del Litoral S.A.", "Farmacia Central", "Textil Patagonia S.A.", "Bodega Los Álamos",
    "Electro Hogar S.R.L.", "Café del Puerto", "Imprenta Moderna", "Transportes Cuyo S.A.",
    "Veterinaria Huellas", "Metalúrgica Río Paraná", "Óptica Visión", "Hotel Las Sierras",
]
NOMBRES = ["Laura Gómez", "Martín Pérez", "Sofía Díaz", "Diego Fernández", "Carla Ruiz", "Pablo Sosa",
           "Valeria Torres", "Andrés Molina", "Julieta Romero", "Federico Castro"]


def generar(semilla: int = 11) -> pd.DataFrame:
    rnd = random.Random(semilla)
    filas = []
    for empresa in EMPRESAS:
        perfil = rnd.choices(["bueno", "regular", "malo"], weights=[5, 3, 2])[0]
        atraso = {"bueno": rnd.randint(1, 20), "regular": rnd.randint(15, 60), "malo": rnd.randint(45, 150)}[perfil]
        filas.append(
            {
                "cliente": empresa,
                "contacto": rnd.choice(NOMBRES),
                "canal": rnd.choice(["WhatsApp", "Email"]),
                "saldo_vencido": round(rnd.uniform(80_000, 6_000_000) * (1.5 if perfil == "malo" else 1), 2),
                "dias_atraso": atraso,
                "facturas_vencidas": rnd.randint(1, 3 if perfil == "bueno" else 7),
                "atraso_promedio_hist": {"bueno": rnd.randint(0, 10), "regular": rnd.randint(10, 35), "malo": rnd.randint(30, 70)}[perfil],
                "promesas_incumplidas": {"bueno": 0, "regular": rnd.randint(0, 1), "malo": rnd.randint(1, 4)}[perfil],
            }
        )
    return pd.DataFrame(filas)


if __name__ == "__main__":
    generar().to_csv("cartera_ejemplo.csv", index=False)
    print("cartera_ejemplo.csv")
