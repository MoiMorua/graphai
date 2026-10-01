from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys
import uuid
from pathlib import Path

from langsmith import utils as ls_utils

from . import credenciales
from .config import cargar_config, grafo_home
from .git import GitError, confirmar, crear_worktree, raiz_git
from .grafo import construir

log = logging.getLogger("grafo")


def ejecutar(args: argparse.Namespace, ap: argparse.ArgumentParser) -> int:
    """Subcomando `run`: ejecuta un ticket (lo que antes era el comando principal)."""
    repo = Path(args.repo).resolve()
    ticket_id = args.id or f"T-{uuid.uuid4().hex[:8]}"
    cfg = cargar_config(args.config, repo)
    log.info("config: %s", " + ".join(str(f) for f in cfg.fuentes))

    # Por defecto el agente trabaja en una rama y un worktree propios, nunca en tu copia de trabajo
    trabajo, rama = repo, None
    if not args.en_sitio:
        raiz = raiz_git(repo)
        if raiz is None:
            ap.error(f"{repo} no es un repo git (o git no está instalado); usa --en-sitio "
                     "para escribir directamente en el directorio")
        try:
            wt, rama = crear_worktree(raiz, ticket_id, grafo_home() / "worktrees")
        except GitError as e:
            ap.error(str(e))
        trabajo = wt / repo.relative_to(raiz)
        log.info("trabajando en la rama %s (worktree %s)", rama, wt)
    else:
        repo.mkdir(parents=True, exist_ok=True)

    estado = {"id": ticket_id, "descripcion": args.descripcion, "repo": str(trabajo),
              "comandos_verify": args.verify or [], "historial": []}
    # run_name/tags/metadata identifican el ticket en LangSmith (si el tracing está activo)
    final = construir(cfg).invoke(estado, {
        "recursion_limit": 500,
        "run_name": f"ticket {ticket_id}",
        "tags": ["grafo", repo.name],
        "metadata": {"ticket": ticket_id, "repo": str(repo), "rama": rama,
                     "descripcion": args.descripcion[:200]},
    })

    hechos = sum(p["estado"] == "hecho" for p in final.get("pasos", []))
    print(f"\n== {ticket_id}: {final['estado_final']} ({final['motivo']})")
    print(f"   pasos {hechos}/{len(final.get('pasos', []))} · iteraciones {final['iteraciones_totales']}"
          f" · consumo Go ${final['consumo_usd']:.4f}")
    print(f"   reporte: {cfg.ruta_tickets / f'{ticket_id}.json'}")
    if proyecto := proyecto_langsmith():
        print(f"   traza:   LangSmith, proyecto '{proyecto}', run 'ticket {ticket_id}'")

    if rama:
        archivos = [(Path(final["repo"]) / a).relative_to(wt).as_posix()
                    for a in dict.fromkeys(final.get("archivos_modificados", []))]
        titulo = args.descripcion.splitlines()[0][:60]
        try:
            commit = confirmar(wt, archivos, f"agente: {titulo}\n\nTicket {ticket_id}: "
                                             f"{final['estado_final']} ({final['motivo']})")
        except GitError as e:
            commit = None
            print(f"   no se pudo commitear: {e}")
        print(f"   rama {rama}" + (f" · commit {commit}" if commit else " · sin cambios"))
        print(f"   revisar:  git diff HEAD...{rama}")
        print(f"   integrar: git merge {rama}")
        print(f"   limpiar:  git worktree remove \"{wt}\"; git branch -D {rama}")
    return 0 if final["estado_final"] == "completado" else 1


def cmd_login(args: argparse.Namespace, ap: argparse.ArgumentParser) -> int:
    clave = args.key or getpass.getpass("Clave de OpenCode Go: ")
    try:
        ruta = credenciales.guardar_clave(clave)
    except ValueError as e:
        ap.error(str(e))
    print(f"clave guardada en {ruta}")
    return 0


def cmd_logout(args: argparse.Namespace, ap: argparse.ArgumentParser) -> int:
    if credenciales.borrar_clave():
        print("clave borrada")
    else:
        print("no había clave guardada")
    return 0


def proyecto_langsmith() -> str | None:
    """Proyecto de LangSmith si el tracing está activo (LANGSMITH_TRACING=true), o None."""
    if not ls_utils.tracing_is_enabled():
        return None
    return ls_utils.get_tracer_project()


def cmd_status(args: argparse.Namespace, ap: argparse.ArgumentParser) -> int:
    cfg = cargar_config(repo=Path.cwd())  # también carga ~/.config/grafo/.env
    print(f"home: {grafo_home()}")
    clave = credenciales.leer_clave()
    if clave:
        print(f"clave OpenCode Go: ****{clave[-4:]}")
    else:
        print("clave OpenCode Go: no guardada")
    if proyecto := proyecto_langsmith():
        sin_clave = "" if os.environ.get("LANGSMITH_API_KEY") else " (¡falta LANGSMITH_API_KEY!)"
        print(f"LangSmith: activo, proyecto '{proyecto}'{sin_clave}")
    else:
        print("LangSmith: inactivo (LANGSMITH_TRACING no es true)")
    print("config cargada:")
    for f in cfg.fuentes:
        print(f"  {f}")
    return 0


def cmd_mermaid(args: argparse.Namespace, ap: argparse.ArgumentParser) -> int:
    print(construir(cargar_config(args.config)).get_graph().draw_mermaid())
    return 0


def construir_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="grafo", description="Grafo agéntico de desarrollo")
    subs = ap.add_subparsers(dest="comando", required=True)

    p_run = subs.add_parser("run", help="ejecuta un ticket en el grafo")
    p_run.add_argument("descripcion", help="texto del ticket")
    p_run.add_argument("--repo", default=".", help="repo donde trabaja el agente (por defecto: .)")
    p_run.add_argument("--id", help="id del ticket (por defecto uno aleatorio)")
    p_run.add_argument("--verify", action="append", metavar="CMD",
                       help="comando de verificación (repetible); por defecto los de la config")
    p_run.add_argument("--config", help="sustituye a ~/.config/grafo/models.yaml")
    p_run.add_argument("--en-sitio", action="store_true",
                       help="escribir directo en --repo en vez de en una rama/worktree aparte")
    p_run.set_defaults(func=ejecutar)

    p_login = subs.add_parser("login", help="guarda la clave de OpenCode Go")
    p_login.add_argument("--key", metavar="CLAVE",
                         help="clave de OpenCode Go (si no se pasa, se pide sin eco)")
    p_login.set_defaults(func=cmd_login)

    p_logout = subs.add_parser("logout", help="borra la clave guardada")
    p_logout.set_defaults(func=cmd_logout)

    p_status = subs.add_parser("status", help="muestra el estado de la configuración")
    p_status.set_defaults(func=cmd_status)

    p_mermaid = subs.add_parser("mermaid", help="imprime el diagrama del grafo y sale")
    p_mermaid.add_argument("--config", help="sustituye a ~/.config/grafo/models.yaml")
    p_mermaid.set_defaults(func=cmd_mermaid)

    return ap


def main() -> int:
    ap = construir_parser()
    args = ap.parse_args()

    for flujo in (sys.stdout, sys.stderr):
        flujo.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    return args.func(args, ap)


if __name__ == "__main__":
    sys.exit(main())
