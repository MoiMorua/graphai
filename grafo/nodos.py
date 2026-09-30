from __future__ import annotations

import copy
import json
import logging
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from .config import Config
from .estado import Paso, Ticket
from .llm import LLMError, Respuesta, extraer_json
from .router import Router, SinModelos

log = logging.getLogger("grafo.nodos")

IGNORAR = {".git", ".grafo", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "logs",
           "dist", "build"}
MAX_CHARS_ARCHIVO = 12_000
RE_ARCHIVO = re.compile(r"^###\s*(?:ARCHIVO:\s*)?`?([^\s`]+)`?\s*\n```[^\n]*\n(.*?)\n```", re.M | re.S)
DECISIONES = ("aceptar", "cambios", "replanificar")

PROMPT_PLAN = """Eres el planificador de un agente de desarrollo. Descompón el ticket en el
MÍNIMO de pasos necesario: una tarea pequeña es UN solo paso. Cada paso es una unidad
funcional completa que incluye su código y sus tests, y deja el repo en estado verificable.
No separes "crear archivo" de "implementar función" ni el código de sus tests.
Responde SOLO con JSON:
{"pasos": [{"descripcion": str, "archivos": [rutas relativas], "dificultad": 1|2|3}]}
Máximo 5 pasos. dificultad: 1 = cambio acotado; 2 = lógica no trivial o varios archivos;
3 = diseño o algoritmo delicado."""

PROMPT_CODEGEN = """Eres un generador de código. Implementa SOLO el paso actual del plan.
Devuelve cada archivo nuevo o modificado COMPLETO, con este formato exacto y sin texto adicional:
### ARCHIVO: ruta/relativa
```
<contenido completo del archivo>
```"""

PROMPT_REVIEW = """Eres revisor de código. Las verificaciones automáticas ya pasaron.
Evalúa SOLO el PASO ACTUAL: lo que corresponde a pasos pendientes del plan se hará después
y no es motivo de rechazo. Si el paso actual está bien hecho, acepta.
Responde SOLO con JSON:
{"decision": "aceptar"|"cambios"|"replanificar", "feedback": str}
Usa "cambios" para problemas concretos del código (explica cuáles).
Usa "replanificar" solo si el plan en sí es incorrecto o incompleto para el ticket."""


class JSONInvalido(ValueError):
    def __init__(self, msg: str, respuestas: list[Respuesta]):
        super().__init__(msg)
        self.respuestas = respuestas


def arbol_repo(repo: Path, limite: int = 300) -> str:
    rutas: list[str] = []
    for raiz, dirs, archivos in os.walk(repo):
        dirs[:] = sorted(d for d in dirs if d not in IGNORAR)
        for a in sorted(archivos):
            rutas.append((Path(raiz) / a).relative_to(repo).as_posix())
            if len(rutas) >= limite:
                return "\n".join(rutas) + "\n…"
    return "\n".join(rutas) or "(repo vacío)"


def ruta_segura(repo: Path, rel: str) -> Path:
    destino = (repo / rel).resolve()
    if not destino.is_relative_to(repo.resolve()):
        raise ValueError(f"ruta fuera del repo: {rel}")
    return destino


def leer(repo: Path, rel: str) -> str | None:
    try:
        return ruta_segura(repo, rel).read_text(encoding="utf-8")[:MAX_CHARS_ARCHIVO]
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def mostrar_archivos(repo: Path, rutas: list[str]) -> str:
    bloques = []
    for r in dict.fromkeys(rutas):
        contenido = leer(repo, r)
        bloques.append(f"### ARCHIVO: {r}\n(no existe)" if contenido is None
                       else f"### ARCHIVO: {r}\n```\n{contenido}\n```")
    return "\n\n".join(bloques) or "(ninguno)"


class Nodos:
    def __init__(self, cfg: Config, router: Router):
        self.cfg = cfg
        self.router = router
        self.lim = cfg.limites

    # ---------- utilidades ----------

    def _llm_json(self, state: Ticket, rol: str, tier: int, sistema: str, usuario: str,
                  max_tokens: int, nodo: str, validar: Callable[[dict], bool]) -> tuple[dict, list[Respuesta]]:
        """Llama al router y reintenta una vez si el JSON no es válido."""
        respuestas: list[Respuesta] = []
        mensaje = usuario
        for _ in range(2):
            r = self.router.llamar(rol, tier, [
                {"role": "system", "content": sistema},
                {"role": "user", "content": mensaje},
            ], ticket_id=state["id"], nodo=nodo, max_tokens=max_tokens)
            respuestas.append(r)
            try:
                d = extraer_json(r.texto)
                if validar(d):
                    return d, respuestas
                error = "estructura inesperada"
            except (ValueError, KeyError, TypeError) as e:
                error = str(e)
            log.warning("%s: JSON inválido (%s), reintento", nodo, error)
            mensaje = f"{usuario}\n\nTu respuesta anterior no era válida ({error}). Responde SOLO con el JSON pedido."
        raise JSONInvalido(f"{nodo}: JSON inválido tras 2 intentos", respuestas)

    @staticmethod
    def _cuenta(state: Ticket, respuestas: list[Respuesta], nodo: str, **detalle) -> dict:
        consumo = sum(r.consumo_usd for r in respuestas)
        ult = respuestas[-1] if respuestas else None
        return {
            "consumo_usd": state.get("consumo_usd", 0.0) + consumo,
            "historial": [{"nodo": nodo, "modelo": ult.modelo if ult else None,
                           "tier": ult.tier if ult else None, "llamadas": len(respuestas),
                           "consumo_usd": round(consumo, 6), **detalle}],
        }

    @staticmethod
    def _plan_txt(pasos: list[Paso], actual: int) -> str:
        marca = lambda p: "[HECHO]" if p["estado"] == "hecho" else "[ACTUAL]" if p["id"] == actual else "[PENDIENTE]"
        return "\n".join(f"{p['id'] + 1}. {marca(p)} {p['descripcion']}" for p in pasos)

    def excede_limites(self, state: Ticket) -> str | None:
        if state.get("iteraciones_totales", 0) >= self.lim["max_iteraciones_ticket"]:
            return f"límite de iteraciones ({self.lim['max_iteraciones_ticket']})"
        if state.get("consumo_usd", 0.0) >= self.lim["max_consumo_ticket_usd"]:
            return f"consumo de Go agotado para el ticket (${self.lim['max_consumo_ticket_usd']})"
        return None

    # ---------- nodos ----------

    def ingesta(self, state: Ticket) -> dict:
        clas, r = self.router.clasificar(state["descripcion"], state["id"])
        log.info("ticket %s: tipo=%s dificultad=%d", state["id"], clas["tipo"], clas["dificultad"])
        return {
            "tipo": clas["tipo"], "tier_plan": clas["dificultad"], "replanificaciones": 0,
            "feedback_plan": None, "pasos": [], "paso_idx": 0, "archivos_escritos": [],
            "fallo": None, "error": None, "iteraciones_totales": 0,
            **self._cuenta({}, [r] if r else [], "ingesta", **clas),
        }

    def plan(self, state: Ticket) -> dict:
        usuario = f"TICKET:\n{state['descripcion']}\n\nARCHIVOS DEL REPO:\n{arbol_repo(Path(state['repo']))}"
        if state.get("feedback_plan"):
            usuario += f"\n\nEL REVISOR RECHAZÓ EL PLAN ANTERIOR:\n{state['feedback_plan']}"

        def valido(d: dict) -> bool:
            return isinstance(d.get("pasos"), list) and len(d["pasos"]) > 0 and all(
                isinstance(p, dict) and p.get("descripcion") for p in d["pasos"])

        try:
            d, rs = self._llm_json(state, "plan", state["tier_plan"], PROMPT_PLAN, usuario,
                                   4000, "plan", valido)
        except JSONInvalido as e:
            return {"error": str(e), **self._cuenta(state, e.respuestas, "plan")}
        except (LLMError, SinModelos) as e:
            return {"error": f"plan: {e}"}

        pasos: list[Paso] = []
        for i, p in enumerate(d["pasos"]):
            try:
                tier = min(max(int(p.get("dificultad", 1)), 1), self.cfg.max_tier)
            except (TypeError, ValueError):
                tier = 1
            pasos.append(Paso(id=i, descripcion=str(p["descripcion"]),
                              archivos=[str(a) for a in p.get("archivos") or []],
                              tier_inicial=tier, tier_actual=tier, intentos_en_tier=0,
                              feedback=[], estado="pendiente"))
        for p in pasos:
            log.info("  paso %d [tier %d] %s", p["id"] + 1, p["tier_inicial"], p["descripcion"])
        return {"pasos": pasos, "paso_idx": 0, "archivos_escritos": [], "error": None,
                **self._cuenta(state, rs, "plan", pasos=len(pasos))}

    def codegen(self, state: Ticket) -> dict:
        repo = Path(state["repo"])
        pasos = copy.deepcopy(state["pasos"])
        paso = pasos[state["paso_idx"]]
        paso["estado"] = "en_curso"

        usuario = (f"TICKET:\n{state['descripcion']}\n\nPLAN:\n{self._plan_txt(pasos, paso['id'])}\n\n"
                   f"PASO ACTUAL ({paso['id'] + 1}): {paso['descripcion']}\n\n"
                   f"ARCHIVOS ACTUALES:\n{mostrar_archivos(repo, paso['archivos'] + state.get('archivos_escritos', []))}")
        if paso["feedback"]:
            usuario += "\n\nERRORES DEL INTENTO ANTERIOR (corrígelos):\n" + "\n\n".join(paso["feedback"][-2:])

        base = {"pasos": pasos, "iteraciones_totales": state.get("iteraciones_totales", 0) + 1}
        try:
            r = self.router.llamar("codegen", paso["tier_actual"], [
                {"role": "system", "content": PROMPT_CODEGEN},
                {"role": "user", "content": usuario},
            ], ticket_id=state["id"], nodo="codegen", max_tokens=16000)
        except SinModelos as e:
            return {**base, "error": f"codegen: {e}"}
        except LLMError as e:
            return {**base, "fallo": f"El modelo no produjo respuesta: {e}",
                    "historial": [{"nodo": "codegen", "error": str(e)}]}

        bloques = RE_ARCHIVO.findall(r.texto)
        if not bloques:
            log.warning("  codegen sin bloques válidos; inicio de la salida:\n%s", r.texto[:400])
            return {**base, "fallo": "No se encontró ningún bloque '### ARCHIVO: ruta' seguido de "
                                     "un bloque de código. Respeta el formato exacto.",
                    **self._cuenta(state, [r], "codegen", archivos=0)}
        escritos: list[str] = []
        for rel, contenido in bloques:
            try:
                destino = ruta_segura(repo, rel)
            except ValueError as e:
                return {**base, "fallo": str(e), **self._cuenta(state, [r], "codegen")}
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(contenido + "\n", encoding="utf-8")
            escritos.append(rel)
        log.info("  paso %d: escritos %s", paso["id"] + 1, escritos)
        return {**base, "fallo": None, "archivos_modificados": escritos,
                "archivos_escritos": list(dict.fromkeys(state.get("archivos_escritos", []) + escritos)),
                **self._cuenta(state, [r], "codegen", archivos=escritos)}

    def verify(self, state: Ticket) -> dict:
        comandos = state.get("comandos_verify") or self.cfg.verify.get("comandos", [])
        codigos_ok = set(self.cfg.verify.get("codigos_ok", [0]))
        errores = []
        for cmd in comandos:
            try:
                p = subprocess.run(cmd, shell=True, cwd=state["repo"], capture_output=True,
                                   text=True, encoding="utf-8", errors="replace",
                                   timeout=self.cfg.verify.get("timeout_s", 300))
                codigo, salida = p.returncode, p.stdout + p.stderr
            except subprocess.TimeoutExpired:
                codigo, salida = -1, "timeout"
            if codigo not in codigos_ok:
                errores.append(f"$ {cmd}  (exit {codigo})\n{salida[-3000:]}")
        ok = not errores
        log.info("  verify: %s", "OK" if ok else f"{len(errores)} comando(s) fallaron")
        return {"verify_ok": ok,
                "fallo": None if ok else "Fallaron las verificaciones:\n" + "\n\n".join(errores),
                "historial": [{"nodo": "verify", "ok": ok}]}

    def fallo(self, state: Ticket) -> dict:
        """Escalado iterativo por paso: N intentos por tier y luego +1 tier."""
        pasos = copy.deepcopy(state["pasos"])
        paso = pasos[state["paso_idx"]]
        paso["feedback"].append(state.get("fallo") or "fallo sin detalle")
        paso["intentos_en_tier"] += 1
        escalado = False
        if paso["intentos_en_tier"] >= self.cfg.tiers[paso["tier_actual"]]["intentos"]:
            paso["tier_actual"] += 1
            paso["intentos_en_tier"] = 0
            escalado = True
            if paso["tier_actual"] <= self.cfg.max_tier:
                log.info("  paso %d: escalado a tier %d", paso["id"] + 1, paso["tier_actual"])
        upd = {"pasos": pasos, "historial": [{"nodo": "fallo", "paso": paso["id"],
                                              "tier": paso["tier_actual"], "escalado": escalado}]}
        if paso["tier_actual"] > self.cfg.max_tier:
            upd["error"] = f"el paso {paso['id'] + 1} agotó todos los tiers"
        return upd

    def review(self, state: Ticket) -> dict:
        repo = Path(state["repo"])
        paso = state["pasos"][state["paso_idx"]]
        usuario = (f"TICKET:\n{state['descripcion']}\n\nPLAN:\n{self._plan_txt(state['pasos'], paso['id'])}\n\n"
                   f"PASO ACTUAL ({paso['id'] + 1}): {paso['descripcion']}\n\n"
                   f"ARCHIVOS RESULTANTES:\n{mostrar_archivos(repo, state.get('archivos_escritos', []))}")
        try:
            d, rs = self._llm_json(state, "review", paso["tier_actual"], PROMPT_REVIEW, usuario,
                                   2000, "review", lambda d: d.get("decision") in DECISIONES)
        except JSONInvalido as e:
            return {"error": str(e), **self._cuenta(state, e.respuestas, "review")}
        except (LLMError, SinModelos) as e:
            return {"error": f"review: {e}"}

        decision, feedback = d["decision"], str(d.get("feedback", ""))
        log.info("  review paso %d: %s %s", paso["id"] + 1, decision, feedback[:120])
        upd = {"decision_review": decision,
               **self._cuenta(state, rs, "review", decision=decision, feedback=feedback)}
        if decision == "cambios":
            upd["fallo"] = f"El revisor pidió cambios:\n{feedback}"
        elif decision == "replanificar":
            upd["feedback_plan"] = feedback
        return upd

    def avanzar(self, state: Ticket) -> dict:
        pasos = copy.deepcopy(state["pasos"])
        pasos[state["paso_idx"]]["estado"] = "hecho"
        return {"pasos": pasos, "paso_idx": state["paso_idx"] + 1, "archivos_escritos": [],
                "historial": [{"nodo": "avanzar", "paso_hecho": state["paso_idx"]}]}

    def replanificar(self, state: Ticket) -> dict:
        n = state.get("replanificaciones", 0) + 1
        upd = {"replanificaciones": n, "archivos_escritos": [],
               "tier_plan": min(state["tier_plan"] + 1, self.cfg.max_tier),
               "historial": [{"nodo": "replanificar", "n": n}]}
        if n > self.lim["max_replanificaciones"]:
            upd["error"] = f"se agotaron las replanificaciones ({self.lim['max_replanificaciones']})"
        return upd

    def humano(self, state: Ticket) -> dict:
        motivo = state.get("error") or self.excede_limites(state) or "desconocido"
        log.warning("ticket %s escalado a humano: %s", state["id"], motivo)
        return self._cerrar(state, "escalado_humano", motivo)

    def fin(self, state: Ticket) -> dict:
        log.info("ticket %s completado", state["id"])
        return self._cerrar(state, "completado", "todos los pasos aceptados")

    def _cerrar(self, state: Ticket, estado: str, motivo: str) -> dict:
        upd = {"estado_final": estado, "motivo": motivo}
        ruta = self.cfg.ruta_tickets / f"{state['id']}.json"
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps({**state, **upd}, ensure_ascii=False, indent=2), encoding="utf-8")
        return upd
