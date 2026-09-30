from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT = Path(__file__).resolve().parent / "models.yaml"


def grafo_home() -> Path:
    """Directorio global del usuario: config, .env con la clave y registro de consumo."""
    return Path(os.environ.get("GRAFO_HOME") or Path.home() / ".config" / "grafo")


def cargar_env(ruta: Path) -> None:
    """Carga KEY=VALOR de un .env sin pisar variables ya definidas."""
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        os.environ.setdefault(clave.strip(), valor.strip().strip("\"'"))


def fusionar(base: dict, extra: dict) -> dict:
    """Fusión profunda: dicts clave a clave; cualquier otro valor (listas incluidas) se reemplaza."""
    salida = dict(base)
    for clave, valor in extra.items():
        if isinstance(valor, dict) and isinstance(salida.get(clave), dict):
            salida[clave] = fusionar(salida[clave], valor)
        else:
            salida[clave] = valor
    return salida


@dataclass
class Config:
    backends: dict
    modelos: dict
    tiers: dict[int, dict]
    tier_min: dict[str, int]
    limites: dict
    verify: dict
    ruta_logs: Path          # global: el consumo de Go es por cuenta, no por repo
    ruta_tickets: Path       # reportes por ticket, dentro del repo destino
    fuentes: list[Path]

    @property
    def max_tier(self) -> int:
        return max(self.tiers)

    def api_key(self, backend: str) -> str:
        b = self.backends[backend]
        return b.get("api_key") or os.environ.get(b.get("api_key_env", ""), "")


def cargar_config(ruta: str | Path | None = None, repo: Path | None = None) -> Config:
    home = grafo_home()
    cargar_env(home / ".env")

    capas = [DEFAULT, Path(ruta) if ruta else home / "models.yaml"]
    if repo:
        capas.append(repo / ".grafo.yaml")
    d: dict = {}
    fuentes = []
    for capa in capas:
        if capa.exists():
            d = fusionar(d, yaml.safe_load(capa.read_text(encoding="utf-8")) or {})
            fuentes.append(capa)
        elif capa == Path(ruta or ""):
            raise FileNotFoundError(f"no existe la config {capa}")

    return Config(
        backends=d["backends"],
        modelos=d["modelos"],
        tiers={int(k): v for k, v in d["tiers"].items()},
        tier_min=d.get("tier_min", {}),
        limites=d["limites"],
        verify=d.get("verify", {}),
        ruta_logs=home / "logs",
        ruta_tickets=(repo / ".grafo" / "tickets") if repo else home / "tickets",
        fuentes=fuentes,
    )
