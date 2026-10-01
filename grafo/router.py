from __future__ import annotations

import logging

from .budget import Libro
from .config import Config
from .llm import Clientes, LLMError, ModeloNoDisponible, Respuesta, extraer_json

log = logging.getLogger("grafo.router")

PROMPT_CLASIFICAR = """Clasifica el ticket de desarrollo. Responde SOLO con JSON:
{"tipo": "bug"|"feature"|"refactor"|"test"|"docs"|"otro", "dificultad": 1|2|3}
1 = cambio acotado en pocos archivos
2 = lógica no trivial o varios módulos
3 = diseño, concurrencia, seguridad o algoritmo delicado"""


class SinModelos(Exception):
    """Ningún modelo disponible puede atender el rol pedido."""


class Router:
    """Sustituto propio de Jev: nivel pedido -> modelo disponible preferido de ese nivel."""

    def __init__(self, cfg: Config, libro: Libro, clientes: Clientes):
        self.cfg = cfg
        self.libro = libro
        self.clientes = clientes

    def disponible(self, clave: str) -> bool:
        m = self.cfg.modelos[clave]
        backend = m["backend"]
        if backend != "local" and not self.cfg.api_key(backend):
            return False
        if tope := m.get("tope_mensual_usd"):
            ventanas = self.cfg.backends[backend].get("ventanas", {})
            return self.libro.dentro_de_tope(clave, tope, ventanas)
        return True

    def elegir(self, rol: str, tier: int, excluidos: set[str] = frozenset()) -> tuple[str, int]:
        maximo = self.cfg.max_tier
        tier = min(max(tier, self.cfg.tier_min.get(rol, 1)), maximo)
        # Primero el tier pedido y los superiores; si no hay nada, los inferiores
        for t in [*range(tier, maximo + 1), *range(tier - 1, 0, -1)]:
            for clave in self.cfg.tiers[t]["modelos"]:
                if (clave not in excluidos and rol in self.cfg.modelos[clave].get("roles", [])
                        and self.disponible(clave)):
                    return clave, t
        raise SinModelos(f"sin modelos para rol={rol} tier={tier} (excluidos: {sorted(excluidos)})")

    def llamar(self, rol: str, tier: int, mensajes: list[dict], *, ticket_id: str, nodo: str,
               max_tokens: int) -> Respuesta:
        excluidos: set[str] = set()
        error_llm: LLMError | None = None
        while True:
            try:
                clave, t = self.elegir(rol, tier, excluidos)
            except SinModelos:
                if error_llm:
                    raise error_llm
                raise
            try:
                r = self.clientes.llamar(clave, mensajes, ticket_id=ticket_id, nodo=nodo,
                                         max_tokens=max_tokens)
                r.tier = t
                return r
            except (ModeloNoDisponible, LLMError) as e:
                log.warning("router: descarto %s para %s: %s", clave, rol, e)
                excluidos.add(clave)
                if isinstance(e, LLMError):
                    error_llm = e

    def clasificar(self, descripcion: str, ticket_id: str) -> tuple[dict, Respuesta | None]:
        try:
            r = self.llamar("clasificar", 1, [
                {"role": "system", "content": PROMPT_CLASIFICAR},
                {"role": "user", "content": descripcion},
            ], ticket_id=ticket_id, nodo="ingesta", max_tokens=200)
            d = extraer_json(r.texto)
            dificultad = min(max(int(d.get("dificultad", 1)), 1), self.cfg.max_tier)
            return {"tipo": str(d.get("tipo", "otro")), "dificultad": dificultad}, r
        except (LLMError, SinModelos, ValueError, TypeError) as e:
            log.warning("clasificación falló (%s); uso heurística", e)
            return {"tipo": "otro", "dificultad": 1 if len(descripcion) < 300 else 2}, None
