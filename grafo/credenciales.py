"""Gestión de credenciales de Grafo (clave de OpenCode Go)."""

from __future__ import annotations

from pathlib import Path

from grafo.config import grafo_home

VARIABLE = "OPENCODE_GO_API_KEY"


def _ruta_env(home: Path | None) -> Path:
    return (home if home is not None else grafo_home()) / ".env"


def _es_linea_variable(linea: str) -> bool:
    return linea.startswith(f"{VARIABLE}=")


def _leer_lineas(ruta: Path) -> list[str]:
    if not ruta.exists():
        return []
    return ruta.read_text(encoding="utf-8").splitlines()


def _escribir_lineas(ruta: Path, lineas: list[str]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    contenido = "\n".join(lineas)
    if contenido:
        contenido += "\n"
    ruta.write_text(contenido, encoding="utf-8")


def guardar_clave(clave: str, home: Path | None = None) -> Path:
    """Guarda la clave en <home>/.env.

    Reemplaza la línea existente de la variable conservando las demás
    líneas; crea el directorio si no existe.

    Args:
        clave: La clave de OpenCode Go a guardar.
        home: Directorio donde está el .env (por defecto grafo_home()).

    Returns:
        La ruta del archivo .env.

    Raises:
        ValueError: Si la clave está vacía o solo tiene espacios.
    """
    if not clave or not clave.strip():
        raise ValueError("La clave no puede estar vacía")
    ruta = _ruta_env(home)
    lineas = [l for l in _leer_lineas(ruta) if not _es_linea_variable(l)]
    lineas.append(f"{VARIABLE}={clave}")
    _escribir_lineas(ruta, lineas)
    return ruta


def leer_clave(home: Path | None = None) -> str | None:
    """Devuelve la clave guardada o None si no hay archivo o no hay línea."""
    ruta = _ruta_env(home)
    for linea in _leer_lineas(ruta):
        if _es_linea_variable(linea):
            return linea.split("=", 1)[1]
    return None


def borrar_clave(home: Path | None = None) -> bool:
    """Elimina solo la línea de la variable.

    Returns:
        True si la línea existía, False en caso contrario.
    """
    ruta = _ruta_env(home)
    if not ruta.exists():
        return False
    lineas = _leer_lineas(ruta)
    nuevas = [l for l in lineas if not _es_linea_variable(l)]
    if len(nuevas) == len(lineas):
        return False
    _escribir_lineas(ruta, nuevas)
    return True
