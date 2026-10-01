"""Tests de grafo.local sin red: se sustituyen la consulta al servidor y el arranque."""
from __future__ import annotations

import io
import json

import pytest

from grafo import local
from grafo.config import cargar_config


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAFO_HOME", str(tmp_path))
    return cargar_config()


def test_es_local():
    assert local.es_local("http://localhost:11434/v1")
    assert local.es_local("http://127.0.0.1:8080/v1")
    assert not local.es_local("https://opencode.ai/zen/go/v1")


def test_modelos_servidos_lee_ids(monkeypatch):
    cuerpo = json.dumps({"data": [{"id": "qwen3-coder:30b"}]}).encode()
    monkeypatch.setattr(local.urllib.request, "urlopen", lambda url, timeout: io.BytesIO(cuerpo))
    assert local.modelos_servidos("http://localhost:11434/v1") == ["qwen3-coder:30b"]


def test_modelos_servidos_none_si_no_responde(monkeypatch):
    def urlopen(url, timeout):
        raise ConnectionRefusedError
    monkeypatch.setattr(local.urllib.request, "urlopen", urlopen)
    assert local.modelos_servidos("http://localhost:11434/v1") is None


def test_ok_si_el_modelo_esta_servido(cfg, monkeypatch):
    monkeypatch.setattr(local, "modelos_servidos", lambda url: ["qwen3-coder:30b"])
    assert local.comprobar_local(cfg) == []


def test_avisa_si_falta_el_modelo(cfg, monkeypatch):
    monkeypatch.setattr(local, "modelos_servidos", lambda url: ["otro:7b"])
    avisos = local.comprobar_local(cfg)
    assert avisos == ["modelo local qwen3-coder:30b no descargado en http://localhost:11434/v1 "
                      "(ollama pull qwen3-coder:30b)"]


def test_inicia_ollama_si_no_responde(cfg, monkeypatch):
    estado = {"arriba": False}
    monkeypatch.setattr(local, "modelos_servidos",
                        lambda url: ["qwen3-coder:30b"] if estado["arriba"] else None)
    monkeypatch.setattr(local.shutil, "which", lambda _: "/bin/ollama")

    def iniciar(url):
        estado["arriba"] = True
        return True
    monkeypatch.setattr(local, "iniciar_ollama", iniciar)

    avisos = local.comprobar_local(cfg)
    assert avisos[0].startswith("modelo local no detectado")
    assert "ollama serve iniciado en localhost:11434" in avisos[1]
    assert len(avisos) == 2


def test_no_inicia_si_iniciar_false(cfg, monkeypatch):
    monkeypatch.setattr(local, "modelos_servidos", lambda url: None)
    monkeypatch.setattr(local, "iniciar_ollama", lambda url: pytest.fail("no debía iniciar"))
    avisos = local.comprobar_local(cfg, iniciar=False)
    assert avisos[0].startswith("modelo local no detectado")
    assert "solo los modelos remotos" in avisos[-1]


def test_avisa_si_ollama_no_esta_en_path(cfg, monkeypatch):
    monkeypatch.setattr(local, "modelos_servidos", lambda url: None)
    monkeypatch.setattr(local.shutil, "which", lambda _: None)
    avisos = local.comprobar_local(cfg)
    assert any("no está en el PATH" in a for a in avisos)
    assert "solo los modelos remotos" in avisos[-1]
