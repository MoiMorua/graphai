import pytest

from grafo import credenciales
from grafo.credenciales import VARIABLE, borrar_clave, guardar_clave, leer_clave


def test_variable_es_opencode_go_api_key():
    assert credenciales.VARIABLE == "OPENCODE_GO_API_KEY"


def test_guardar_crea_archivo_y_leer_devuelve_clave(tmp_path):
    ruta = guardar_clave("sk-test-1234", home=tmp_path)
    assert ruta == tmp_path / ".env"
    assert ruta.exists()
    assert leer_clave(home=tmp_path) == "sk-test-1234"


def test_guardar_crea_directorio_si_no_existe(tmp_path):
    home = tmp_path / "anidado" / "home"
    ruta = guardar_clave("clave", home=home)
    assert ruta.exists()
    assert leer_clave(home=home) == "clave"


def test_guardar_reemplaza_sin_perder_otras_lineas(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "OTRA_VAR=valor\nOPENCODE_GO_API_KEY=vieja\nFOO=bar\n",
        encoding="utf-8",
    )
    guardar_clave("nueva", home=tmp_path)
    contenido = env.read_text(encoding="utf-8")
    assert "OTRA_VAR=valor" in contenido
    assert "FOO=bar" in contenido
    assert "vieja" not in contenido
    assert leer_clave(home=tmp_path) == "nueva"
    lineas = [l for l in contenido.splitlines() if l.startswith(f"{VARIABLE}=")]
    assert len(lineas) == 1


def test_borrar_elimina_solo_esa_linea_y_devuelve_true(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "OTRA_VAR=valor\nOPENCODE_GO_API_KEY=clave\n",
        encoding="utf-8",
    )
    assert borrar_clave(home=tmp_path) is True
    contenido = env.read_text(encoding="utf-8")
    assert "OPENCODE_GO_API_KEY" not in contenido
    assert "OTRA_VAR=valor" in contenido
    assert leer_clave(home=tmp_path) is None


def test_borrar_sin_linea_devuelve_false(tmp_path):
    env = tmp_path / ".env"
    env.write_text("OTRA_VAR=valor\n", encoding="utf-8")
    assert borrar_clave(home=tmp_path) is False
    assert env.read_text(encoding="utf-8") == "OTRA_VAR=valor\n"


def test_borrar_sin_archivo_devuelve_false(tmp_path):
    assert borrar_clave(home=tmp_path) is False


def test_leer_sin_archivo_devuelve_none(tmp_path):
    assert leer_clave(home=tmp_path) is None


def test_guardar_clave_vacia_lanza_value_error(tmp_path):
    with pytest.raises(ValueError):
        guardar_clave("", home=tmp_path)
    with pytest.raises(ValueError):
        guardar_clave("   ", home=tmp_path)
