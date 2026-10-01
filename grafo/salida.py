"""Aplica la salida del modelo al repositorio.

Formatos reconocidos en el texto del modelo:
    ### ARCHIVO: ruta   (seguido de un bloque de código) -> escribe el archivo
    ### MOVER: viejo -> nuevo                            -> renombra/mueve
    ### BORRAR: ruta                                     -> elimina
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

RE_ARCHIVO = re.compile(
    r"^###\s*(?:ARCHIVO:\s*)?`?([^\s`]+)`?\s*\n```[^\n]*\n(.*?)\n```",
    re.M | re.S,
)
RE_MOVER = re.compile(
    r"^###\s*MOVER:\s*`?([^\s`]+)`?\s*->\s*`?([^\s`]+)`?\s*$",
    re.M,
)
RE_BORRAR = re.compile(
    r"^###\s*BORRAR:\s*`?([^\s`]+)`?\s*$",
    re.M,
)


def ruta_segura(repo: Path, rel: str) -> Path:
    """Resuelve repo/rel y garantiza que la ruta queda dentro del repo."""
    repo = Path(repo).resolve()
    ruta = (repo / rel).resolve()
    try:
        ruta.relative_to(repo)
    except ValueError:
        raise ValueError(f"ruta fuera del repo: {rel}") from None
    return ruta


def aplicar_salida(repo: Path, texto: str) -> list[str]:
    """Aplica los bloques MOVER, BORRAR y ARCHIVO de `texto` sobre `repo`.

    Valida TODAS las operaciones antes de tocar el disco: si alguna es
    inválida se lanza ValueError y el repositorio queda sin cambios.
    La aplicación se hace en orden MOVER -> BORRAR -> ARCHIVO.

    Devuelve la lista de rutas relativas tocadas, sin duplicados y en
    orden de aplicación (un move aporta viejo y nuevo).
    """
    moves = RE_MOVER.findall(texto)
    deletes = RE_BORRAR.findall(texto)
    writes = RE_ARCHIVO.findall(texto)

    if not moves and not deletes and not writes:
        return []

    # --- Validación completa (sin tocar el disco) ---
    # Simula el efecto de cada operación para detectar conflictos entre ellas
    # (p. ej. borrar el origen de un MOVER o mover dos veces al mismo destino).
    creados: set[Path] = set()
    quitados: set[Path] = set()

    def existe(p: Path) -> bool:
        return p in creados or (p not in quitados and p.is_file())

    val_moves = []
    for viejo, nuevo in moves:
        p_viejo = ruta_segura(repo, viejo)
        p_nuevo = ruta_segura(repo, nuevo)
        if not existe(p_viejo):
            raise ValueError(f"no existe: {viejo}")
        if existe(p_nuevo) or p_nuevo.is_dir():
            raise ValueError(f"ya existe: {nuevo}")
        creados.discard(p_viejo)
        quitados.add(p_viejo)
        quitados.discard(p_nuevo)
        creados.add(p_nuevo)
        val_moves.append((viejo, nuevo, p_viejo, p_nuevo))

    val_deletes = []
    for rel in deletes:
        p = ruta_segura(repo, rel)
        if not existe(p):
            raise ValueError(f"no existe: {rel}")
        creados.discard(p)
        quitados.add(p)
        val_deletes.append((rel, p))

    val_writes = []
    for rel, contenido in writes:
        p = ruta_segura(repo, rel)
        if p.is_dir():
            raise ValueError(f"es un directorio: {rel}")
        val_writes.append((rel, p, contenido))

    # --- Aplicación en orden: MOVER -> BORRAR -> ARCHIVO ---
    tocadas: list[str] = []

    def marcar(rel: str) -> None:
        if rel not in tocadas:
            tocadas.append(rel)

    for viejo, nuevo, p_viejo, p_nuevo in val_moves:
        p_nuevo.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p_viejo), str(p_nuevo))
        marcar(viejo)
        marcar(nuevo)

    for rel, p in val_deletes:
        p.unlink()
        marcar(rel)

    for rel, p, contenido in val_writes:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(contenido + "\n", encoding="utf-8")
        marcar(rel)

    return tocadas
