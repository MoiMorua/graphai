"""Versión instalada y actualización a los releases publicados en GitHub."""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from urllib.parse import quote, urlparse

PAQUETE = "grafo-agentico"
REPO = "MoiMorua/graphai"
API = f"https://api.github.com/repos/{REPO}"


@dataclass
class Instalacion:
    version: str
    modo: str               # "editable" | "git" | "otro"
    origen: str             # ruta del clon (editable) o URL del repo (git)
    revision: str | None    # tag o commit instalado (git)

    def describir(self) -> str:
        if self.modo == "editable":
            return f"grafo {self.version} (editable desde {self.origen})"
        if self.modo == "git":
            return f"grafo {self.version} ({self.origen}@{self.revision})"
        return f"grafo {self.version}"


def instalacion() -> Instalacion:
    """Lee cómo se instaló el paquete a partir de su direct_url.json (PEP 610)."""
    dist = metadata.distribution(PAQUETE)
    try:
        du = json.loads(dist.read_text("direct_url.json") or "{}")
    except json.JSONDecodeError:
        du = {}
    if du.get("dir_info", {}).get("editable"):
        return Instalacion(dist.version, "editable", url_a_ruta(du["url"]), None)
    if "vcs_info" in du:
        vcs = du["vcs_info"]
        revision = vcs.get("requested_revision") or vcs.get("commit_id", "")[:8]
        return Instalacion(dist.version, "git", du["url"], revision)
    return Instalacion(dist.version, "otro", du.get("url", ""), None)


def url_a_ruta(url: str) -> str:
    return urllib.request.url2pathname(urlparse(url).path) if url.startswith("file:") else url


def parsear_version(v: str) -> tuple[int, int, int]:
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", v.strip())
    if not m:
        raise ValueError(f"versión no válida: {v!r} (se espera vX.Y.Z)")
    return int(m[1]), int(m[2]), int(m[3])


def _api(ruta: str, timeout: float = 10) -> dict:
    req = urllib.request.Request(f"{API}/{ruta}", headers={
        "Accept": "application/vnd.github+json", "User-Agent": PAQUETE})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def ultimo_release() -> str:
    """Tag del último release publicado (p. ej. 'v0.2.0'). Lanza OSError si no hay o no responde."""
    try:
        return _api("releases/latest")["tag_name"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise OSError("aún no hay releases publicados") from e
        raise


def existe_release(tag: str) -> bool:
    try:
        _api(f"releases/tags/{quote(tag)}")
        return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise


def comando_instalar(tag: str) -> list[str]:
    """Comando de uv que instala (o reemplaza) grafo con el release `tag`."""
    uv = shutil.which("uv")
    if not uv:
        raise FileNotFoundError("no se encontró uv en el PATH")
    return [uv, "tool", "install", "--force", f"git+https://github.com/{REPO}.git@{tag}"]


def instalar_al_salir(cmd: list[str], log: Path) -> None:
    """Ejecuta `cmd` cuando termine este proceso, en segundo plano.

    En Windows uv no puede reemplazar el entorno de la herramienta mientras grafo.exe
    está corriendo (lo intenta, falla a medias y deja grafo roto). Un PowerShell aparte
    espera a que salgamos y entonces ejecuta uv, con la salida en `log`.
    """
    log.parent.mkdir(parents=True, exist_ok=True)

    def q(s: object) -> str:
        return "'" + str(s).replace("'", "''") + "'"

    script = "\n".join([
        f"Wait-Process -Id {os.getpid()} -ErrorAction SilentlyContinue",
        "Start-Sleep -Seconds 2",  # deja salir también al lanzador grafo.exe
        f"$p = Start-Process -FilePath {q(cmd[0])} -ArgumentList {','.join(q(a) for a in cmd[1:])}"
        f" -RedirectStandardOutput {q(f'{log}.out')} -RedirectStandardError {q(log)}"
        " -NoNewWindow -Wait -PassThru",
        f"Add-Content -Path {q(log)} -Value \"exit $($p.ExitCode)\"",
    ])
    args = ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand",
            base64.b64encode(script.encode("utf-16-le")).decode()]
    # CREATE_NO_WINDOW (consola oculta), no DETACHED_PROCESS: PowerShell sin consola sale al instante
    flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    # Si la terminal mete a grafo en un job object, el hijo moriría con nosotros:
    # pedimos salir del job y, si el job no lo permite, lo lanzamos igual.
    for extra in (subprocess.CREATE_BREAKAWAY_FROM_JOB, 0):
        try:
            subprocess.Popen(args, creationflags=flags | extra, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
            return
        except PermissionError:
            continue
