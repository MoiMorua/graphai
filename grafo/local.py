"""Detección y arranque del servidor del modelo local (Ollama u otro OpenAI-compatible)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlparse

from .config import Config

HOSTS_LOCALES = {"localhost", "127.0.0.1", "::1"}


def es_local(base_url: str) -> bool:
    return urlparse(base_url).hostname in HOSTS_LOCALES


def modelos_servidos(base_url: str, timeout: float = 2.0) -> list[str] | None:
    """Ids de GET <base_url>/models, o None si el servidor no responde."""
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/models", timeout=timeout) as r:
            datos = json.load(r)
    except (OSError, ValueError):
        return None
    return [m.get("id", "") for m in datos.get("data", [])]


def iniciar_ollama(base_url: str, espera_s: float = 30.0) -> bool:
    """Lanza `ollama serve` desacoplado en el host:puerto de base_url y espera a que responda."""
    exe = shutil.which("ollama")
    if not exe:
        return False
    env = {**os.environ, "OLLAMA_HOST": urlparse(base_url).netloc}
    if sys.platform == "win32":
        opciones = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        opciones = {"start_new_session": True}
    subprocess.Popen([exe, "serve"], env=env, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **opciones)
    limite = time.monotonic() + espera_s
    while time.monotonic() < limite:
        if modelos_servidos(base_url) is not None:
            return True
        time.sleep(0.5)
    return False


def comprobar_local(cfg: Config, iniciar: bool = True) -> list[str]:
    """Comprueba los backends locales que usa algún modelo; devuelve los avisos a mostrar.

    Si el servidor no responde y el backend tiene `iniciar: ollama`, intenta arrancarlo.
    """
    avisos = []
    for nombre, b in cfg.backends.items():
        url = b["base_url"]
        modelos = [m["model"] for m in cfg.modelos.values() if m["backend"] == nombre]
        if not modelos or not es_local(url):
            continue

        servidos = modelos_servidos(url)
        if servidos is None:
            avisos.append(f"modelo local no detectado: {url} no responde")
            if iniciar and b.get("iniciar") == "ollama":
                if shutil.which("ollama") is None:
                    avisos.append("  ollama no está en el PATH; instálalo o arranca el servidor a mano")
                elif iniciar_ollama(url):
                    avisos.append(f"  ollama serve iniciado en {urlparse(url).netloc}")
                    servidos = modelos_servidos(url)
                else:
                    avisos.append("  ollama serve no respondió a tiempo")
            if servidos is None:
                avisos.append("  sin modelo local: el router usará solo los modelos remotos")
                continue

        for m in modelos:
            if m not in servidos and f"{m}:latest" not in servidos:
                avisos.append(f"modelo local {m} no descargado en {url} (ollama pull {m})")
    return avisos
