import pytest

from grafo.output import aplicar_salida


def test_mover_renombra_y_conserva_contenido(tmp_path):
    (tmp_path / "a.txt").write_text("hola\n", encoding="utf-8")

    tocadas = aplicar_salida(tmp_path, "### MOVER: a.txt -> docs/b.txt\n")

    assert not (tmp_path / "a.txt").exists()
    assert (tmp_path / "docs" / "b.txt").read_text(encoding="utf-8") == "hola\n"
    assert tocadas == ["a.txt", "docs/b.txt"]


def test_mover_y_archivo_reescribe_el_movido(tmp_path):
    (tmp_path / "a.txt").write_text("viejo\n", encoding="utf-8")
    texto = (
        "### MOVER: a.txt -> b.txt\n"
        "### ARCHIVO: b.txt\n"
        "```\n"
        "nuevo\n"
        "```\n"
    )

    tocadas = aplicar_salida(tmp_path, texto)

    assert not (tmp_path / "a.txt").exists()
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "nuevo\n"
    assert tocadas == ["a.txt", "b.txt"]  # b.txt aparece una sola vez


def test_borrar_elimina(tmp_path):
    (tmp_path / "a.txt").write_text("x\n", encoding="utf-8")

    tocadas = aplicar_salida(tmp_path, "### BORRAR: a.txt\n")

    assert not (tmp_path / "a.txt").exists()
    assert tocadas == ["a.txt"]


def test_borrar_inexistente_lanza(tmp_path):
    with pytest.raises(ValueError, match="no existe: a.txt"):
        aplicar_salida(tmp_path, "### BORRAR: a.txt\n")


def test_ruta_fuera_del_repo_no_toca_disco(tmp_path):
    (tmp_path / "a.txt").write_text("original\n", encoding="utf-8")
    texto = (
        "### ARCHIVO: b.txt\n"
        "```\n"
        "contenido\n"
        "```\n"
        "### ARCHIVO: ../fuera.txt\n"
        "```\n"
        "mal\n"
        "```\n"
    )

    with pytest.raises(ValueError, match="ruta fuera del repo"):
        aplicar_salida(tmp_path, texto)

    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "original\n"
    assert not (tmp_path / "b.txt").exists()
    assert not (tmp_path.parent / "fuera.txt").exists()


def test_mover_inexistente_no_aplica_nada(tmp_path):
    (tmp_path / "a.txt").write_text("x\n", encoding="utf-8")
    texto = "### MOVER: noexiste.txt -> b.txt\n### BORRAR: a.txt\n"

    with pytest.raises(ValueError, match="no existe: noexiste.txt"):
        aplicar_salida(tmp_path, texto)

    assert (tmp_path / "a.txt").exists()
    assert not (tmp_path / "b.txt").exists()


def test_mover_sobre_existente_lanza(tmp_path):
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b\n", encoding="utf-8")

    with pytest.raises(ValueError, match="ya existe: b.txt"):
        aplicar_salida(tmp_path, "### MOVER: a.txt -> b.txt\n")

    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "a\n"
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "b\n"


def test_borrar_origen_de_un_mover_lanza_sin_tocar_disco(tmp_path):
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")

    with pytest.raises(ValueError, match="no existe: a.txt"):
        aplicar_salida(tmp_path, "### MOVER: a.txt -> b.txt\n### BORRAR: a.txt\n")

    assert (tmp_path / "a.txt").exists()
    assert not (tmp_path / "b.txt").exists()


def test_dos_mover_al_mismo_destino_lanza(tmp_path):
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    (tmp_path / "c.txt").write_text("c\n", encoding="utf-8")

    with pytest.raises(ValueError, match="ya existe: b.txt"):
        aplicar_salida(tmp_path, "### MOVER: a.txt -> b.txt\n### MOVER: c.txt -> b.txt\n")

    assert (tmp_path / "a.txt").exists()
    assert not (tmp_path / "b.txt").exists()


def test_mover_encadenado_y_borrar_el_destino(tmp_path):
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")

    tocadas = aplicar_salida(tmp_path, "### MOVER: a.txt -> b.txt\n### BORRAR: b.txt\n")

    assert not (tmp_path / "a.txt").exists()
    assert not (tmp_path / "b.txt").exists()
    assert tocadas == ["a.txt", "b.txt"]


def test_borrar_directorio_lanza(tmp_path):
    (tmp_path / "d").mkdir()

    with pytest.raises(ValueError, match="no existe: d"):
        aplicar_salida(tmp_path, "### BORRAR: d\n")

    assert (tmp_path / "d").is_dir()


def test_lista_devuelta_incluye_viejo_y_nuevo(tmp_path):
    (tmp_path / "a.txt").write_text("x\n", encoding="utf-8")

    tocadas = aplicar_salida(tmp_path, "### MOVER: a.txt -> b.txt\n")

    assert "a.txt" in tocadas
    assert "b.txt" in tocadas


def test_sin_bloques_devuelve_lista_vacia(tmp_path):
    assert aplicar_salida(tmp_path, "salida sin ningún bloque\n") == []
