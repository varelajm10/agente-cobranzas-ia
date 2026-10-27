"""Interfaz web: streamlit run app.py"""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from agente import Redactor, explicar, puntuar, validar
from agente.demo import generar
from agente.redactor import formato_pesos

st.set_page_config(page_title="Agente de cobranzas", page_icon="🤖", layout="wide")

COLORES = {"Crítico": "🔴", "Alto": "🟠", "Medio": "🟡", "Bajo": "🟢"}

st.title("🤖 Agente de IA de cobranzas")
st.caption("Prioriza tu cartera por riesgo y te deja listo el mensaje para cada cliente. Vos solo revisás y enviás.")

with st.sidebar:
    st.header("Cartera")
    usar_demo = st.toggle("Usar cartera de ejemplo", value=True)
    archivo = st.file_uploader("Cartera vencida (CSV/Excel)", type=["csv", "xlsx"], disabled=usar_demo)
    st.header("Agente")
    hay_key = bool(os.getenv("ANTHROPIC_API_KEY"))
    usar_ia = st.toggle("Redactar con IA (Claude)", value=hay_key, disabled=not hay_key,
                        help="Configurá ANTHROPIC_API_KEY para activarlo. Sin clave usa plantillas por segmento.")
    if not hay_key:
        st.caption("Modo plantillas activo: configurá `ANTHROPIC_API_KEY` para mensajes personalizados.")
    link = st.text_input("Link de pago", "https://pagar.tuempresa.com/abc123")

if usar_demo:
    df = generar()
elif archivo:
    df = pd.read_excel(archivo) if archivo.name.endswith("xlsx") else pd.read_csv(archivo)
else:
    st.info("Subí tu cartera vencida o activá la cartera de ejemplo.")
    st.stop()

try:
    cartera = puntuar(df)
except ValueError as e:
    st.error(str(e))
    st.stop()

# --- KPIs ---------------------------------------------------------------------
c1, c2, c3, c4 = st.columns(4)
c1.metric("Saldo vencido", formato_pesos(cartera["saldo_vencido"].sum()).split(",")[0])
c2.metric("Clientes con deuda", len(cartera))
criticos = cartera[cartera["segmento"].isin(["Crítico", "Alto"])]
c3.metric("Saldo en riesgo alto/crítico", formato_pesos(criticos["saldo_vencido"].sum()).split(",")[0], help=f"{len(criticos)} clientes")
c4.metric("Atraso promedio", f"{cartera['dias_atraso'].mean():.0f} días")

# --- Cola priorizada ----------------------------------------------------------------
st.subheader("Cola de gestión de hoy")
vista = cartera.assign(
    riesgo=cartera["segmento"].map(lambda s: f"{COLORES[s]} {s}"),
    motivo=cartera.apply(explicar, axis=1),
)[["riesgo", "cliente", "saldo_vencido", "dias_atraso", "puntaje", "motivo", "canal"]]
st.dataframe(
    vista,
    hide_index=True,
    use_container_width=True,
    column_config={
        "saldo_vencido": st.column_config.NumberColumn("saldo vencido", format="$ %.0f"),
        "dias_atraso": st.column_config.NumberColumn("días", format="%d"),
        "puntaje": st.column_config.ProgressColumn("puntaje", min_value=0, max_value=100, format="%d"),
    },
)

# --- Redacción --------------------------------------------------------------------
st.subheader("Mensaje sugerido")
cliente = st.selectbox("Cliente", cartera["cliente"], format_func=lambda c: f"{COLORES[cartera.set_index('cliente').loc[c, 'segmento']]} {c}")
fila = cartera.set_index("cliente").loc[cliente].copy()
fila["cliente"] = cliente

clave = f"prop_{cliente}_{usar_ia}"
if clave not in st.session_state:
    with st.spinner("El agente está redactando..."):
        st.session_state[clave] = Redactor(usar_ia=usar_ia).redactar(fila)
prop = st.session_state[clave]

izq, der = st.columns([3, 2])
with izq:
    if prop.asunto:
        st.text_input("Asunto", prop.asunto)
    texto = st.text_area(f"Mensaje por {prop.canal}", prop.mensaje.replace("{LINK_PAGO}", link), height=220)
    problemas = validar(texto.replace(link, "{LINK_PAGO}"), fila)
    if problemas:
        st.warning("Revisá el mensaje: " + "; ".join(problemas))
    else:
        st.success("Mensaje validado: tono correcto, saldo exacto y link de pago incluidos.")
with der:
    st.markdown(f"**Segmento:** {COLORES[prop.segmento]} {prop.segmento} · puntaje {int(fila['puntaje'])}/100")
    st.markdown(f"**Por qué:** {prop.motivo}")
    st.markdown(f"**Acción:** {prop.accion}")
    st.markdown(f"**Próximo paso:** {prop.proximo_paso}")
    st.caption(f"Redactado con: {prop.origen}")
    if st.button("🔄 Regenerar"):
        del st.session_state[clave]
        st.rerun()

# --- Exportar plan -------------------------------------------------------------------
st.divider()
top = st.slider("Clientes a incluir en el plan del día", 3, len(cartera), min(10, len(cartera)))
if st.button("📋 Generar plan de cobranza del día", type="primary"):
    with st.spinner("Preparando mensajes..."):
        plan = Redactor(usar_ia=usar_ia).plan_del_dia(cartera, top=top)
        plan["mensaje"] = plan["mensaje"].str.replace("{LINK_PAGO}", link, regex=False)
    st.dataframe(plan[["segmento", "cliente", "canal", "accion", "proximo_paso", "mensaje"]], hide_index=True, use_container_width=True)
    st.download_button("⬇️ Descargar plan (CSV)", plan.to_csv(index=False).encode("utf-8-sig"), "plan_cobranza.csv")
