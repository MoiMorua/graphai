from __future__ import annotations

import argparse
import logging
import sys
import uuid
from pathlib import Path

from .config import cargar_config, grafo_home
from .git import GitError, confirmar, crear_worktree, raiz_git
from .grafo import construir

log = logging.getLogger("grafo")


def main() -> int:
    ap = argparse.ArgumentParser(prog="grafo", description="Grafo agéntico de desarrollo")
    ap.add_argument("descripcion", nargs="?", help="texto del ticket")
    ap.add_argument("--repo", default=".", help="repo donde trabaja el agente (por defecto: .)")
    ap.add_argument("--id", help="id del ticket (por defecto uno aleatorio)")
    ap.add_argument("--verify", action="append", metavar="CMD",
                    help="comando de verificación (repetible); por defecto los de la config")
    ap.add_argument("--config", help="sustituye a ~/.config/grafo/models.yaml")
    ap.add_argument("--en-sitio", action="store_true",
                    help="escribir directo en --repo en vez de en una rama/worktree aparte")
    ap.add_argument("--mermaid", action="store_true", help="imprime el diagrama del grafo y sale")
    args = ap.parse_args()

    for flujo in (sys.stdout, sys.stderr):
        flujo.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if args.mermaid:
        print(construir(cargar_config(args.config)).get_graph().draw_mermaid())
        return 0
    if not args.descripcion:
        ap.error("falta la descripción del ticket")

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
    final = construir(cfg).invoke(estado, {"recursion_limit": 500})

    hechos = sum(p["estado"] == "hecho" for p in final.get("pasos", []))
    print(f"\n== {ticket_id}: {final['estado_final']} ({final['motivo']})")
    print(f"   pasos {hechos}/{len(final.get('pasos', []))} · iteraciones {final['iteraciones_totales']}"
          f" · consumo Go ${final['consumo_usd']:.4f}")
    print(f"   reporte: {cfg.ruta_tickets / f'{ticket_id}.json'}")

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


if __name__ == "__main__":
    sys.exit(main())
