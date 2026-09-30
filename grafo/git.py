"""Aislamiento del trabajo del agente: una rama y un worktree por ticket."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class GitError(Exception):
    pass


def _git(cwd: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode:
        raise GitError(f"git {' '.join(args)}: {p.stderr.strip()}")
    return p.stdout.strip()


def raiz_git(ruta: Path) -> Path | None:
    """Raíz del repo git que contiene `ruta`, o None si no hay git o no es un repo."""
    if not shutil.which("git"):
        return None
    try:
        return Path(_git(ruta, "rev-parse", "--show-toplevel")).resolve()
    except GitError:
        return None


def crear_worktree(raiz: Path, ticket_id: str, base: Path) -> tuple[Path, str]:
    """Crea la rama agente/<id> desde HEAD en un worktree aparte. Devuelve (ruta, rama)."""
    rama = f"agente/{ticket_id}"
    destino = base / raiz.name / ticket_id
    destino.parent.mkdir(parents=True, exist_ok=True)
    _git(raiz, "worktree", "add", "-b", rama, str(destino), "HEAD")
    return destino, rama


def confirmar(worktree: Path, archivos: list[str], mensaje: str) -> str | None:
    """Commitea solo los archivos que escribió el agente. Devuelve el hash corto o None."""
    if not archivos:
        return None
    _git(worktree, "add", "--", *archivos)
    if not _git(worktree, "diff", "--cached", "--name-only"):
        return None
    _git(worktree, "commit", "-m", mensaje)
    return _git(worktree, "rev-parse", "--short", "HEAD")
