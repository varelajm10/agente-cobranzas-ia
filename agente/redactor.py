"""Agente redactor: decide la acción y escribe el mensaje de cobranza para cada cliente.

Funciona en dos modos:
- **Con IA** (si hay ANTHROPIC_API_KEY): Claude redacta un mensaje personalizado y
  devuelve JSON estructurado. La salida se valida con reglas de negocio.
- **Sin IA**: plantillas por segmento. Es también el respaldo si la IA falla o si
  su mensaje no pasa la validación, así el proceso nunca se corta.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass

import pandas as pd

from .riesgo import explicar

MODELO_POR_DEFECTO = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5")

PALABRAS_PROHIBIDAS = [  # tono: firme sí, amenazante nunca
    "embargo", "juicio", "denuncia", "veraz", "moroso", "deudor incobrable", "amenaza", "última vez",
]

SISTEMA = """Sos un analista senior de créditos y cobranzas de una pyme argentina.
Redactás mensajes de cobranza B2B: claros, respetuosos y orientados a cobrar sin romper la relación comercial.
Reglas:
- Español rioplatense neutro y profesional ("usted" en email, "vos" solo si el canal es WhatsApp).
- Mencioná SIEMPRE el saldo exacto y la cantidad de facturas.
- Incluí el marcador {LINK_PAGO} donde va el link de pago.
- Nunca amenaces ni menciones acciones legales, Veraz, embargos o juicios.
- WhatsApp: máximo 450 caracteres. Email: máximo 900 caracteres y con asunto.
- Ajustá la firmeza al segmento de riesgo y proponé un próximo paso concreto con fecha.
Respondé SOLO con JSON: {"accion": str, "asunto": str, "mensaje": str, "proximo_paso": str}"""


@dataclass
class Propuesta:
    cliente: str
    segmento: str
    canal: str
    accion: str
    asunto: str
    mensaje: str
    proximo_paso: str
    motivo: str
    origen: str  # "IA" o "Plantilla"

    def dict(self) -> dict:
        return asdict(self)


def formato_pesos(valor: float) -> str:
    return "$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ---------------------------------------------------------------------------
# Plantillas (modo sin IA y respaldo)
# ---------------------------------------------------------------------------

# (acción, asunto, mensaje WhatsApp, mensaje email, próximo paso)
PLANTILLAS = {
    "Bajo": (
        "Recordatorio amable",
        "Recordatorio de pago - {cliente}",
        "Hola {contacto}, ¿cómo va? Te recuerdo que tenés {n} factura{s} vencida{s} por {saldo}. "
        "Si ya la abonaste, desestimá este mensaje. Si no, podés pagar acá: {{LINK_PAGO}}. ¡Gracias!",
        "Estimado/a {contacto}:\n\nLe recordamos que {cliente} tiene {n} factura{s} vencida{s} por {saldo}. "
        "Si ya realizó el pago, le pedimos que desestime este mensaje. De lo contrario, puede abonar aquí: {{LINK_PAGO}}.\n\nMuchas gracias.",
        "Verificar acreditación en 5 días",
    ),
    "Medio": (
        "Recordatorio con detalle",
        "Saldo vencido de {cliente}: {saldo}",
        "Hola {contacto}. Tenemos {n} factura{s} vencida{s} por {saldo}, con {dias} días de atraso. "
        "¿Me confirmás la fecha de pago? Podés abonar acá: {{LINK_PAGO}}.",
        "Estimado/a {contacto}:\n\nRegistramos {n} factura{s} vencida{s} de {cliente} por un total de {saldo}, "
        "con {dias} días de atraso. ¿Podría confirmarnos la fecha estimada de pago? Puede abonar directamente aquí: {{LINK_PAGO}}.\n\nSaludos cordiales.",
        "Llamar si no hay respuesta en 3 días",
    ),
    "Alto": (
        "Seguimiento firme + plan de pagos",
        "Regularización de saldo pendiente - {cliente}",
        "Hola {contacto}. El saldo vencido es de {saldo} ({n} factura{s}, {dias} días de atraso) y necesitamos "
        "regularizarlo esta semana. Si te sirve, armamos un plan de pagos. Link: {{LINK_PAGO}}. ¿Hablamos mañana?",
        "Estimado/a {contacto}:\n\nEl saldo vencido de {cliente} asciende a {saldo} ({n} factura{s}, {dias} días de atraso). "
        "Necesitamos regularizarlo durante esta semana. Si le resulta útil, podemos acordar un plan de pagos en cuotas. "
        "Link de pago: {{LINK_PAGO}}.\n\n¿Podemos coordinar una llamada mañana?",
        "Llamada de seguimiento en 48 h; proponer plan de pagos",
    ),
    "Crítico": (
        "Escalamiento a responsable",
        "Urgente: saldo vencido de {cliente} por {saldo}",
        "Hola {contacto}. El saldo vencido es de {saldo} ({n} factura{s}, {dias} días). Para mantener la cuenta "
        "operativa necesitamos acordar hoy una fecha de pago o un plan. Link: {{LINK_PAGO}}. ¿Te llamo hoy?",
        "Estimado/a {contacto}:\n\nEl saldo vencido de {cliente} es de {saldo}, correspondiente a {n} factura{s} "
        "con {dias} días de atraso. Para mantener la cuenta operativa necesitamos acordar hoy una fecha de pago "
        "o un plan de regularización. Puede abonar aquí: {{LINK_PAGO}}.\n\nQuedo a disposición para una llamada.",
        "Llamada del responsable de créditos hoy; evaluar suspensión de despachos",
    ),
}


def redactar_plantilla(fila: pd.Series) -> Propuesta:
    accion, asunto, cuerpo_wa, cuerpo_mail, paso = PLANTILLAS[fila["segmento"]]
    es_mail = fila["canal"] == "Email"
    n = int(fila["facturas_vencidas"])
    datos = {
        "cliente": fila["cliente"],
        "contacto": str(fila["contacto"]).split()[0],
        "saldo": formato_pesos(fila["saldo_vencido"]),
        "n": n,
        "s": "s" if n != 1 else "",
        "dias": int(fila["dias_atraso"]),
    }
    return Propuesta(
        cliente=fila["cliente"],
        segmento=fila["segmento"],
        canal=fila["canal"],
        accion=accion,
        asunto=asunto.format(**datos) if es_mail else "",
        mensaje=(cuerpo_mail if es_mail else cuerpo_wa).format(**datos),
        proximo_paso=paso,
        motivo=explicar(fila),
        origen="Plantilla",
    )


# ---------------------------------------------------------------------------
# Validación de la salida de la IA
# ---------------------------------------------------------------------------

def validar(mensaje: str, fila: pd.Series) -> list[str]:
    """Devuelve la lista de problemas. Lista vacía = mensaje aprobado."""
    problemas = []
    texto = mensaje.lower()
    for palabra in PALABRAS_PROHIBIDAS:
        if palabra in texto:
            problemas.append(f"usa una expresión no permitida: '{palabra}'")
    if "{link_pago}" not in texto:
        problemas.append("falta el link de pago")
    # el saldo tiene que figurar (se acepta con o sin decimales)
    entero = f"{int(fila['saldo_vencido']):,}".replace(",", ".")
    if entero not in mensaje:
        problemas.append("no menciona el saldo exacto")
    limite = 450 if fila["canal"] == "WhatsApp" else 900
    if len(mensaje) > limite:
        problemas.append(f"supera {limite} caracteres")
    return problemas


def _extraer_json(texto: str) -> dict:
    m = re.search(r"\{.*\}", texto, re.S)
    if not m:
        raise ValueError("la respuesta no contiene JSON")
    return json.loads(m.group(0))


# ---------------------------------------------------------------------------
# Agente
# ---------------------------------------------------------------------------

class Redactor:
    def __init__(self, cliente_llm=None, modelo: str = MODELO_POR_DEFECTO, usar_ia: bool | None = None):
        """cliente_llm: un anthropic.Anthropic() o cualquier objeto con la misma interfaz (útil en tests)."""
        if usar_ia is None:
            usar_ia = cliente_llm is not None or bool(os.getenv("ANTHROPIC_API_KEY"))
        self.usar_ia = usar_ia
        self.modelo = modelo
        self._llm = cliente_llm
        self.errores: list[str] = []

    @property
    def llm(self):
        if self._llm is None:
            import anthropic

            self._llm = anthropic.Anthropic()
        return self._llm

    def _prompt(self, fila: pd.Series) -> str:
        return (
            f"Cliente: {fila['cliente']}\n"
            f"Contacto: {fila['contacto']}\n"
            f"Canal: {fila['canal']}\n"
            f"Saldo vencido: {formato_pesos(fila['saldo_vencido'])}\n"
            f"Facturas vencidas: {int(fila['facturas_vencidas'])}\n"
            f"Días de atraso: {int(fila['dias_atraso'])}\n"
            f"Atraso promedio histórico: {int(fila['atraso_promedio_hist'])} días\n"
            f"Promesas de pago incumplidas: {int(fila['promesas_incumplidas'])}\n"
            f"Segmento de riesgo: {fila['segmento']} (puntaje {int(fila['puntaje'])}/100)\n"
            f"Estrategia sugerida: {fila['estrategia']}\n"
            f"Motivo del puntaje: {explicar(fila)}"
        )

    def redactar(self, fila: pd.Series) -> Propuesta:
        if not self.usar_ia:
            return redactar_plantilla(fila)
        try:
            resp = self.llm.messages.create(
                model=self.modelo,
                max_tokens=700,
                system=SISTEMA,
                messages=[{"role": "user", "content": self._prompt(fila)}],
            )
            datos = _extraer_json(resp.content[0].text)
            problemas = validar(datos["mensaje"], fila)
            if problemas:
                raise ValueError("; ".join(problemas))
            return Propuesta(
                cliente=fila["cliente"],
                segmento=fila["segmento"],
                canal=fila["canal"],
                accion=datos.get("accion", ""),
                asunto=datos.get("asunto", "") if fila["canal"] == "Email" else "",
                mensaje=datos["mensaje"],
                proximo_paso=datos.get("proximo_paso", ""),
                motivo=explicar(fila),
                origen="IA",
            )
        except Exception as e:  # la cobranza no se frena por un error de la IA
            self.errores.append(f"{fila['cliente']}: {e}")
            return redactar_plantilla(fila)

    def plan_del_dia(self, cartera_puntuada: pd.DataFrame, top: int | None = None) -> pd.DataFrame:
        filas = cartera_puntuada.head(top) if top else cartera_puntuada
        return pd.DataFrame([self.redactar(f).dict() for _, f in filas.iterrows()])
