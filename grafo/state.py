from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict


class Paso(TypedDict):
    id: int
    descripcion: str
    archivos: list[str]
    tier_inicial: int          # asignado por el plan
    tier_actual: int
    intentos_en_tier: int
    feedback: list[str]        # errores de verify / review para el siguiente intento
    huella: str | None         # hash de lo escrito en el último codegen
    huella_anterior: str | None
    repeticiones: int          # intentos seguidos con la misma salida y el mismo error
    ultimo_error: str | None   # último fallo normalizado, para detectar errores repetidos
    diagnosticados: list[str]  # hashes de los errores ya enviados a diagnóstico
    estado: Literal["pendiente", "en_curso", "hecho"]


class Ticket(TypedDict, total=False):
    # Entrada
    id: str
    descripcion: str
    repo: str
    comandos_verify: list[str]

    # Clasificación y plan
    tipo: str
    tier_plan: int
    replanificaciones: int
    feedback_plan: str | None
    pasos: list[Paso]
    paso_idx: int

    # Paso en curso
    archivos_escritos: list[str]
    archivos_modificados: Annotated[list[str], operator.add]   # todo el ticket (para el commit)
    fallo: str | None           # motivo del último fallo (codegen, verify o review)
    diagnosticar: bool          # el fallo pide pasar por el nodo de diagnóstico
    verify_ok: bool
    decision_review: Literal["aceptar", "cambios", "replanificar"]

    # Contabilidad y guardas
    iteraciones_totales: int
    consumo_usd: float          # consumo de topes de Go a precio de lista
    error: str | None           # fallo no recuperable -> escalado a humano
    historial: Annotated[list[dict], operator.add]

    # Salida
    estado_final: Literal["completado", "escalado_humano"]
    motivo: str
