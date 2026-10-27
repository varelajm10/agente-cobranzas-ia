import json
from types import SimpleNamespace

import pandas as pd
import pytest

from agente import Redactor, puntuar, validar
from agente.demo import generar
from agente.riesgo import segmento_de


def cartera(**cambios):
    base = {
        "cliente": "Acme S.A.", "contacto": "Laura Gómez", "canal": "WhatsApp", "saldo_vencido": 1_500_000.0,
        "dias_atraso": 30, "facturas_vencidas": 2, "atraso_promedio_hist": 10, "promesas_incumplidas": 0,
    }
    filas = [base, {**base, "cliente": "Ref", "saldo_vencido": 100_000.0}]
    filas[0].update(cambios)
    return pd.DataFrame(filas)


class LLMFalso:
    """Imita anthropic.Anthropic().messages.create devolviendo un texto fijo."""

    def __init__(self, texto):
        self.texto = texto
        self.llamadas = []
        self.messages = self

    def create(self, **kw):
        self.llamadas.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(text=self.texto)])


# --- riesgo ------------------------------------------------------------------

def test_mas_atraso_implica_mas_puntaje():
    bajo = puntuar(cartera(dias_atraso=5)).set_index("cliente").loc["Acme S.A.", "puntaje"]
    alto = puntuar(cartera(dias_atraso=110)).set_index("cliente").loc["Acme S.A.", "puntaje"]
    assert alto > bajo


def test_promesas_incumplidas_suben_el_riesgo():
    sin = puntuar(cartera(promesas_incumplidas=0)).set_index("cliente").loc["Acme S.A.", "puntaje"]
    con = puntuar(cartera(promesas_incumplidas=3)).set_index("cliente").loc["Acme S.A.", "puntaje"]
    assert con - sin == 15  # peso de promesas = 15 puntos


@pytest.mark.parametrize("p,seg", [(0, "Bajo"), (24, "Bajo"), (25, "Medio"), (50, "Alto"), (75, "Crítico"), (100, "Crítico")])
def test_segmentos(p, seg):
    assert segmento_de(p) == seg


def test_prioriza_por_riesgo_y_monto():
    c = puntuar(generar())
    assert c["prioridad"].is_monotonic_decreasing
    assert c["puntaje"].between(0, 100).all()


def test_columnas_faltantes():
    with pytest.raises(ValueError, match="faltan columnas"):
        puntuar(pd.DataFrame({"cliente": ["x"]}))


# --- validación ----------------------------------------------------------------

def test_validar_detecta_amenazas_y_falta_de_link():
    fila = puntuar(cartera()).iloc[0]
    problemas = validar("Si no paga iniciamos juicio por $ 1.500.000", fila)
    assert any("juicio" in p for p in problemas)
    assert any("link" in p for p in problemas)


def test_plantillas_siempre_pasan_la_validacion():
    c = puntuar(generar())
    r = Redactor(usar_ia=False)
    for _, fila in c.iterrows():
        p = r.redactar(fila)
        assert validar(p.mensaje, fila) == [], (fila["cliente"], fila["canal"])
        assert p.origen == "Plantilla"
        assert (p.asunto != "") == (fila["canal"] == "Email")


# --- agente con IA ---------------------------------------------------------------

def test_usa_la_respuesta_de_la_ia_si_es_valida():
    fila = puntuar(cartera()).iloc[0]
    respuesta = json.dumps({
        "accion": "Recordatorio",
        "asunto": "",
        "mensaje": "Hola Laura, tenés 2 facturas vencidas por $ 1.500.000,00. Podés pagar acá: {LINK_PAGO}",
        "proximo_paso": "Llamar el jueves",
    })
    llm = LLMFalso("Acá va:\n" + respuesta)
    p = Redactor(cliente_llm=llm).redactar(fila)
    assert p.origen == "IA" and p.proximo_paso == "Llamar el jueves"
    assert "Acme S.A." in llm.llamadas[0]["messages"][0]["content"]


def test_si_la_ia_amenaza_vuelve_a_la_plantilla():
    fila = puntuar(cartera()).iloc[0]
    malo = json.dumps({"accion": "x", "asunto": "", "mensaje": "Pague $ 1.500.000 o vamos a juicio {LINK_PAGO}", "proximo_paso": ""})
    r = Redactor(cliente_llm=LLMFalso(malo))
    p = r.redactar(fila)
    assert p.origen == "Plantilla"
    assert "juicio" in r.errores[0]


def test_si_la_ia_no_devuelve_json_vuelve_a_la_plantilla():
    fila = puntuar(cartera()).iloc[0]
    r = Redactor(cliente_llm=LLMFalso("no sé"))
    assert r.redactar(fila).origen == "Plantilla"
    assert r.errores


def test_plan_del_dia_respeta_el_top():
    plan = Redactor(usar_ia=False).plan_del_dia(puntuar(generar()), top=5)
    assert len(plan) == 5
    assert {"cliente", "mensaje", "proximo_paso", "origen"} <= set(plan.columns)
