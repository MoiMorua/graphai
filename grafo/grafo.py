from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .config import Config, cargar_config
from .estado import Ticket
from .llm import Clientes
from .nodos import Nodos
from .presupuesto import Libro
from .router import Router


def construir(cfg: Config | None = None):
    cfg = cfg or cargar_config()
    libro = Libro(cfg.ruta_logs / "uso.jsonl")
    router = Router(cfg, libro, Clientes(cfg, libro))
    n = Nodos(cfg, router)

    g = StateGraph(Ticket)
    for nombre in ("ingesta", "plan", "codegen", "verify", "fallo", "review",
                   "avanzar", "replanificar", "humano", "fin"):
        g.add_node(nombre, getattr(n, nombre))

    def tras_plan(s: Ticket) -> str:
        return "humano" if s.get("error") else "codegen"

    def tras_codegen(s: Ticket) -> str:
        if s.get("error"):
            return "humano"
        return "fallo" if s.get("fallo") else "verify"

    def tras_verify(s: Ticket) -> str:
        if n.excede_limites(s):
            return "humano"
        return "review" if s["verify_ok"] else "fallo"

    def tras_fallo(s: Ticket) -> str:
        return "humano" if s.get("error") or n.excede_limites(s) else "codegen"

    def tras_review(s: Ticket) -> str:
        if s.get("error"):
            return "humano"
        return {"aceptar": "avanzar", "cambios": "fallo",
                "replanificar": "replanificar"}[s["decision_review"]]

    def tras_avanzar(s: Ticket) -> str:
        return "codegen" if s["paso_idx"] < len(s["pasos"]) else "fin"

    def tras_replanificar(s: Ticket) -> str:
        return "humano" if s.get("error") else "plan"

    g.add_edge(START, "ingesta")
    g.add_edge("ingesta", "plan")
    g.add_conditional_edges("plan", tras_plan, ["codegen", "humano"])
    g.add_conditional_edges("codegen", tras_codegen, ["verify", "fallo", "humano"])
    g.add_conditional_edges("verify", tras_verify, ["review", "fallo", "humano"])
    g.add_conditional_edges("fallo", tras_fallo, ["codegen", "humano"])
    g.add_conditional_edges("review", tras_review, ["avanzar", "fallo", "replanificar", "humano"])
    g.add_conditional_edges("avanzar", tras_avanzar, ["codegen", "fin"])
    g.add_conditional_edges("replanificar", tras_replanificar, ["plan", "humano"])
    g.add_edge("humano", END)
    g.add_edge("fin", END)
    return g.compile()
