from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime

import openai
from openai import OpenAI

from .config import Config
from .budget import Libro

log = logging.getLogger("grafo.llm")


class ModeloNoDisponible(Exception):
    """El modelo no puede atender la llamada (tope, contexto, auth, slug); el router elige otro."""


class LLMError(Exception):
    """Fallo persistente tras agotar los reintentos."""


@dataclass
class Respuesta:
    texto: str
    modelo: str
    tokens_in: int
    tokens_out: int
    consumo_usd: float        # a precio de lista; en Go se descuenta del tope mensual
    tier: int = 0


def extraer_json(texto: str) -> dict:
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto.strip())
    ini, fin = t.find("{"), t.rfind("}")
    if ini < 0 or fin < ini:
        raise ValueError("no hay objeto JSON en la respuesta")
    return json.loads(t[ini : fin + 1])


class Clientes:
    """Un cliente OpenAI-compatible por backend, con reintentos y registro de costo."""

    def __init__(self, cfg: Config, libro: Libro):
        self.cfg = cfg
        self.libro = libro
        self._clientes: dict[str, OpenAI] = {}

    def _cliente(self, backend: str) -> OpenAI:
        if backend not in self._clientes:
            b = self.cfg.backends[backend]
            self._clientes[backend] = OpenAI(
                base_url=b["base_url"],
                api_key=self.cfg.api_key(backend) or "sin-clave",
                default_headers=b.get("headers") or None,
                timeout=self.cfg.limites["timeout_llamada_s"],
                max_retries=0,  # los reintentos los controlamos aquí
            )
        return self._clientes[backend]

    def llamar(self, clave: str, mensajes: list[dict], *, ticket_id: str, nodo: str,
               max_tokens: int) -> Respuesta:
        m = self.cfg.modelos[clave]
        backend = m["backend"]
        b = self.cfg.backends[backend]

        # Guard de contexto explícito (~3 caracteres por token, estimación conservadora)
        if num_ctx := b.get("num_ctx"):
            estimado = sum(len(x["content"]) for x in mensajes) // 3 + max_tokens
            if estimado > num_ctx:
                raise ModeloNoDisponible(f"~{estimado} tokens > num_ctx {num_ctx}")

        extra_headers = {b["session_header"]: ticket_id} if b.get("session_header") else None

        ultimo: Exception | None = None
        for intento in range(self.cfg.limites["max_reintentos_llamada"]):
            t0 = time.monotonic()
            try:
                r = self._cliente(backend).chat.completions.create(
                    model=m["model"], messages=mensajes, max_tokens=max_tokens,
                    temperature=0.2, extra_headers=extra_headers,
                )
            except openai.RateLimitError as e:
                raise ModeloNoDisponible(f"tope alcanzado ({e.status_code})") from e
            except (openai.AuthenticationError, openai.PermissionDeniedError,
                    openai.NotFoundError, openai.BadRequestError) as e:
                raise ModeloNoDisponible(f"{type(e).__name__}: {e}") from e
            except (openai.APIConnectionError, openai.APITimeoutError,
                    openai.InternalServerError) as e:
                ultimo = e
            else:
                texto = (r.choices[0].message.content or "").strip() if r.choices else ""
                if texto:
                    if r.choices[0].finish_reason == "length":
                        log.warning("%s: salida cortada por max_tokens=%d", clave, max_tokens)
                    return self._registrar(clave, backend, r, texto, ticket_id, nodo,
                                           time.monotonic() - t0)
                # Qwen a veces emite un preámbulo vacío/cortado: reintentar
                ultimo = LLMError(f"respuesta vacía (finish_reason={r.choices[0].finish_reason if r.choices else None})")
            espera = 2 ** intento
            log.warning("%s: %s — reintento en %ss", clave, ultimo, espera)
            time.sleep(espera)
        raise LLMError(f"{clave}: {ultimo}")

    def _registrar(self, clave: str, backend: str, r, texto: str, ticket_id: str, nodo: str,
                   segundos: float) -> Respuesta:
        precio = self.cfg.modelos[clave].get("precio", {})
        u = r.usage
        tin = (u.prompt_tokens if u else 0) or 0
        tout = (u.completion_tokens if u else 0) or 0
        consumo = (tin * precio.get("in", 0) + tout * precio.get("out", 0)) / 1e6

        self.libro.anotar({
            "ts": time.time(), "fecha": datetime.now().isoformat(timespec="seconds"),
            "ticket": ticket_id, "nodo": nodo, "modelo": clave, "backend": backend,
            "model_real": r.model, "tokens_in": tin, "tokens_out": tout,
            "consumo_usd": consumo, "segundos": round(segundos, 2),
        })
        log.info("%-8s %-13s in=%-6d out=%-6d consumo=$%.4f %.1fs",
                 nodo, clave, tin, tout, consumo, segundos)
        return Respuesta(texto, clave, tin, tout, consumo)

