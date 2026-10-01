from __future__ import annotations

import json
import time
from pathlib import Path

VENTANAS_H = {"5h": 5, "7d": 24 * 7, "30d": 24 * 30}


class Libro:
    """Registro append-only de cada llamada (logs/uso.jsonl).

    Sirve para medir ahorro y para saber cuánto tope de Go queda en cada ventana.
    """

    def __init__(self, ruta: Path):
        self.ruta = ruta
        ruta.parent.mkdir(parents=True, exist_ok=True)

    def anotar(self, registro: dict) -> None:
        with self.ruta.open("a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")

    def _registros(self, modelo: str, desde_ts: float) -> list[dict]:
        if not self.ruta.exists():
            return []
        salida = []
        with self.ruta.open(encoding="utf-8") as f:
            for linea in f:
                try:
                    r = json.loads(linea)
                except json.JSONDecodeError:
                    continue
                if r.get("modelo") == modelo and r.get("ts", 0) >= desde_ts:
                    salida.append(r)
        return salida

    def dentro_de_tope(self, modelo: str, tope_usd: float, ventanas: dict[str, float]) -> bool:
        """True si el consumo (a precio de lista) está bajo el tope en todas las ventanas."""
        ahora = time.time()
        horas_max = max(VENTANAS_H[v] for v in ventanas) if ventanas else 0
        registros = self._registros(modelo, ahora - horas_max * 3600)
        for ventana, fraccion in ventanas.items():
            desde = ahora - VENTANAS_H[ventana] * 3600
            gasto = sum(r.get("consumo_usd", 0) for r in registros if r["ts"] >= desde)
            if gasto >= fraccion * tope_usd:
                return False
        return True
