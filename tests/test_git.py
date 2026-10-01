"""Tests de grafo.git.confirmar con un repo git real en tmp_path."""
from __future__ import annotations

import subprocess
from pathlib import Path

from grafo.git import confirmar


def _git(cwd: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert p.returncode == 0, f"git {' '.join(args)}: {p.stderr}"
    return p.stdout.strip()


def _repo_con_a_txt(tmp_path: Path) -> Path:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / "a.txt").write_text("hola\n", encoding="utf-8")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-m", "inicial")
    return tmp_path


def test_confirmar_renombrado(tmp_path):
    _repo_con_a_txt(tmp_path)
    (tmp_path / "a.txt").rename(tmp_path / "b.txt")

    h = confirmar(tmp_path, ["a.txt", "b.txt"], "renombra a -> b")

    assert h
    assert _git(tmp_path, "ls-files").splitlines() == ["b.txt"]


def test_confirmar_ruta_inexistente_no_trackeada_devuelve_none(tmp_path):
    _repo_con_a_txt(tmp_path)

    assert confirmar(tmp_path, ["nunca_existio.txt"], "msg") is None
