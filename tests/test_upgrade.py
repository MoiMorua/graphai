import io
import json
import urllib.error

import pytest

from grafo import upgrade as actualizar


class DistFalsa:
    def __init__(self, version, direct_url):
        self.version = version
        self._du = direct_url

    def read_text(self, nombre):
        assert nombre == "direct_url.json"
        return None if self._du is None else json.dumps(self._du)


def instalar_falsa(monkeypatch, version, direct_url):
    monkeypatch.setattr(actualizar.metadata, "distribution", lambda _: DistFalsa(version, direct_url))


@pytest.mark.parametrize("texto, esperado", [
    ("v1.2.3", (1, 2, 3)), ("0.10.0", (0, 10, 0)), (" v2.0.1 ", (2, 0, 1)),
])
def test_parsear_version(texto, esperado):
    assert actualizar.parsear_version(texto) == esperado


@pytest.mark.parametrize("texto", ["1.2", "v1.2.3-rc1", "latest", ""])
def test_parsear_version_invalida(texto):
    with pytest.raises(ValueError):
        actualizar.parsear_version(texto)


def test_versiones_se_comparan_numericamente():
    assert actualizar.parsear_version("v0.10.0") > actualizar.parsear_version("v0.9.9")


def test_instalacion_editable(monkeypatch, tmp_path):
    instalar_falsa(monkeypatch, "0.1.0", {"url": tmp_path.as_uri(), "dir_info": {"editable": True}})
    inst = actualizar.instalacion()
    assert (inst.modo, inst.version) == ("editable", "0.1.0")
    assert inst.origen == str(tmp_path)
    assert "editable" in inst.describir()


def test_instalacion_git_con_tag(monkeypatch):
    instalar_falsa(monkeypatch, "0.2.0", {
        "url": "https://github.com/MoiMorua/graphai.git",
        "vcs_info": {"vcs": "git", "requested_revision": "v0.2.0", "commit_id": "abc123def456"}})
    inst = actualizar.instalacion()
    assert (inst.modo, inst.revision) == ("git", "v0.2.0")
    assert inst.describir() == "grafo 0.2.0 (https://github.com/MoiMorua/graphai.git@v0.2.0)"


def test_instalacion_git_sin_tag_usa_commit(monkeypatch):
    instalar_falsa(monkeypatch, "0.2.0", {
        "url": "https://github.com/MoiMorua/graphai.git",
        "vcs_info": {"vcs": "git", "commit_id": "abc123def456"}})
    assert actualizar.instalacion().revision == "abc123de"


def test_instalacion_sin_direct_url(monkeypatch):
    instalar_falsa(monkeypatch, "0.3.0", None)
    assert actualizar.instalacion().describir() == "grafo 0.3.0"


def test_ultimo_release(monkeypatch):
    def urlopen(req, timeout):
        assert req.full_url.endswith("/releases/latest")
        return io.BytesIO(json.dumps({"tag_name": "v0.4.0"}).encode())
    monkeypatch.setattr(actualizar.urllib.request, "urlopen", urlopen)
    assert actualizar.ultimo_release() == "v0.4.0"


def test_existe_release_404(monkeypatch):
    def urlopen(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
    monkeypatch.setattr(actualizar.urllib.request, "urlopen", urlopen)
    assert actualizar.existe_release("v9.9.9") is False


def test_comando_instalar_apunta_al_tag(monkeypatch):
    monkeypatch.setattr(actualizar.shutil, "which", lambda _: "/bin/uv")
    assert actualizar.comando_instalar("v0.2.0") == [
        "/bin/uv", "tool", "install", "--force", "git+https://github.com/MoiMorua/graphai.git@v0.2.0"]
