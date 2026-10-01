from __future__ import annotations

import argparse
import getpass
import logging
import subprocess
import sys
import uuid
from pathlib import Path

from . import actualizar, credenciales
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


def cmd_status(args: argparse.Namespace, ap: argparse.ArgumentParser) -> int:
    print(f"home: {grafo_home()}")
    clave = credenciales.leer_clave()
    if clave:
        print(f"clave OpenCode Go: ****{clave[-4:]}")
    else:
        print("clave OpenCode Go: no guardada")
    cfg = cargar_config(repo=Path.cwd())
    print("config cargada:")
    for f in cfg.fuentes:
        print(f"  {f}")
    return 0


def cmd_upgrade(args: argparse.Namespace, ap: argparse.ArgumentParser) -> int:
    inst = actualizar.instalacion()
    print(f"instalado: {inst.describir()}")
    try:
        objetivo = args.version or actualizar.ultimo_release()
        nueva = actualizar.parsear_version(objetivo)
    except ValueError as e:
        ap.error(str(e))
    except OSError as e:
        print(f"no se pudo consultar el último release de {actualizar.REPO}: {e}")
        return 1
    objetivo = "v" + objetivo.removeprefix("v")

    if not args.version and nueva <= actualizar.parsear_version(inst.version):
        print(f"ya tienes la última versión ({objetivo})")
        return 0
    if args.check:
        print(f"disponible: {objetivo} (instálala con: grafo upgrade)")
        return 0
    if inst.modo == "editable" and not args.forzar:
        print(f"es una instalación editable: el código sale de {inst.origen}.\n"
              f"  seguir el release en el clon: git -C \"{inst.origen}\" fetch --tags; "
              f"git -C \"{inst.origen}\" checkout {objetivo}\n"
              f"  pasar a instalación por releases: grafo upgrade --forzar")
        return 1
    if not actualizar.existe_release(objetivo):
        print(f"no existe el release {objetivo} en {actualizar.REPO}")
        return 1

    cmd = actualizar.comando_instalar(objetivo)
    if sys.platform == "win32":
        log_ = grafo_home() / "logs" / "upgrade.log"
        actualizar.instalar_al_salir(cmd, log_)
        print(f"instalando {objetivo} en segundo plano en cuanto termine este comando.\n"
              f"  log: {log_}\n  comprueba con: grafo --version")
        return 0
    return subprocess.run(cmd).returncode


def cmd_mermaid(args: argparse.Namespace, ap: argparse.ArgumentParser) -> int:
    print(construir(cargar_config(args.config)).get_graph().draw_mermaid())
    return 0


def construir_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="grafo", description="Grafo agéntico de desarrollo")
    ap.add_argument("--version", action="version", version=actualizar.instalacion().describir())
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

    p_upgrade = subs.add_parser("upgrade", help="actualiza grafo al último release de GitHub")
    p_upgrade.add_argument("version", nargs="?", help="release concreto (vX.Y.Z); por defecto el último")
    p_upgrade.add_argument("--check", action="store_true", help="solo comprueba si hay versión nueva")
    p_upgrade.add_argument("--forzar", action="store_true",
                           help="reemplaza también una instalación editable por la del release")
    p_upgrade.set_defaults(func=cmd_upgrade)

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
