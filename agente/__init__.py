"""Agente de IA para priorizar la cartera y redactar mensajes de cobranza."""

from .redactor import Propuesta, Redactor, validar
from .riesgo import explicar, puntuar

__all__ = ["Propuesta", "Redactor", "validar", "explicar", "puntuar"]
__version__ = "1.0.0"
