import sys
from pathlib import Path

from grafo.config import Config
from grafo.llm import Respuesta
from grafo.nodos import (
    AVISO_REPETICION,
    Nodos,
    huella,
    normalizar_error,
    pistas,
    recortar,
)
from grafo.router import SinModelos


class RouterFalso:
    def __init__(self, texto: str):
        self.texto = texto
        self.mensajes: list[list[dict]] = []

    def llamar(self, rol, tier, mensajes, **_):
        self.mensajes.append(mensajes)
        return Respuesta(texto=self.texto, modelo="falso", tokens_in=0, tokens_out=0,
                         consumo_usd=0.0, tier=tier)


def config(intentos: int = 3) -> Config:
    return Config(backends={}, modelos={}, tiers={1: {"intentos": intentos}, 2: {"intentos": intentos}},
                  tier_min={}, limites={}, verify={"comandos": [], "codigos_ok": [0]},
                  ruta_logs=Path("."), ruta_tickets=Path("."), fuentes=[])


def paso(**extra) -> dict:
    return {"id": 0, "descripcion": "crear calc", "archivos": ["calc.py"], "tier_inicial": 1,
            "tier_actual": 1, "intentos_en_tier": 0, "feedback": [], "huella": None,
            "huella_anterior": None, "repeticiones": 0, "ultimo_error": None, "diagnosticados": [],
            "estado": "en_curso", **extra}


def ticket(repo: Path, **extra) -> dict:
    return {"id": "T-x", "descripcion": "ticket", "repo": str(repo), "paso_idx": 0,
            "archivos_escritos": [], **extra}


# ---------- pistas ----------

def test_pistas_reconoce_errores_de_importacion_de_varios_lenguajes():
    for salida in ["E   ModuleNotFoundError: No module named 'calc'",
                   "Error: Cannot find module './calc'",
                   "error[E0432]: unresolved import `crate::calc`",
                   "no required module provides package example.com/calc"]:
        assert len(pistas(salida)) == 1 and "importación" in pistas(salida)[0], salida


def test_pistas_reconoce_comando_inexistente():
    assert pistas("sh: pytest: command not found")
    assert pistas("'pytest' is not recognized as an internal or external command")


def test_pistas_no_marca_fallos_de_logica():
    assert pistas("AssertionError: assert 4 == 5") == []


# ---------- huella / normalizar ----------

def test_huella_cambia_con_el_contenido_y_con_borrados(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    h1 = huella(tmp_path, ["a.py"])
    assert huella(tmp_path, ["a.py"]) == h1
    (tmp_path / "a.py").write_text("x = 2\n", encoding="utf-8")
    h2 = huella(tmp_path, ["a.py"])
    assert h2 != h1
    (tmp_path / "a.py").unlink()
    assert huella(tmp_path, ["a.py"]) not in (h1, h2)


def test_normalizar_error_ignora_duraciones():
    assert normalizar_error("1 error in 0.10s") == normalizar_error("1 error in 0.08s")
    assert normalizar_error("1 error") != normalizar_error("2 errors")


# ---------- codegen ----------

def test_codegen_muestra_el_arbol_del_repo_y_guarda_huella(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    router = RouterFalso("### ARCHIVO: calc.py\n```\nx = 1\n```\n")
    upd = Nodos(config(), router).codegen(ticket(tmp_path, pasos=[paso(huella="vieja")]))

    usuario = router.mensajes[0][1]["content"]
    assert "ARCHIVOS DEL REPO:" in usuario and "pyproject.toml" in usuario
    p = upd["pasos"][0]
    assert p["huella_anterior"] == "vieja"
    assert p["huella"] == huella(tmp_path, ["calc.py"])


def test_codegen_sin_bloques_deja_huella_vacia(tmp_path):
    upd = Nodos(config(), RouterFalso("no sé")).codegen(ticket(tmp_path, pasos=[paso(huella="vieja")]))
    assert upd["pasos"][0]["huella"] is None


# ---------- verify ----------

def test_verify_antepone_pistas_al_error(tmp_path):
    cmd = f'"{sys.executable}" -c "import sys; print(\'ModuleNotFoundError: x\'); sys.exit(1)"'
    upd = Nodos(config(), RouterFalso("")).verify(ticket(tmp_path, comandos_verify=[cmd]))
    assert not upd["verify_ok"]
    assert "PISTA: Error de importación" in upd["fallo"]


# ---------- fallo ----------

ERROR = "Fallaron las verificaciones:\nModuleNotFoundError: calc\n1 error in 0.10s"


def test_fallo_avisa_en_la_primera_repeticion_y_escala_en_la_segunda(tmp_path):
    nodos = Nodos(config(intentos=5), RouterFalso(""))
    p = paso(huella="h", huella_anterior="otra")
    upd = nodos.fallo(ticket(tmp_path, pasos=[p], fallo=ERROR))
    p = upd["pasos"][0]
    assert p["repeticiones"] == 0 and not p["feedback"][-1].startswith("AVISO")

    # mismo código y mismo error (con otra duración): aviso
    p["huella_anterior"] = "h"
    upd = nodos.fallo(ticket(tmp_path, pasos=[p], fallo=ERROR.replace("0.10s", "0.09s")))
    p = upd["pasos"][0]
    assert p["repeticiones"] == 1 and p["feedback"][-1].startswith(AVISO_REPETICION)
    assert p["tier_actual"] == 1

    # se repite otra vez: escala aunque queden intentos en el tier
    upd = nodos.fallo(ticket(tmp_path, pasos=[p], fallo=ERROR))
    p = upd["pasos"][0]
    assert p["tier_actual"] == 2 and p["intentos_en_tier"] == 0 and p["repeticiones"] == 0


def test_fallo_no_cuenta_repeticion_si_cambia_el_codigo_o_el_error(tmp_path):
    nodos = Nodos(config(), RouterFalso(""))
    p = paso(huella="h1", huella_anterior="h0", feedback=[ERROR], ultimo_error=normalizar_error(ERROR))
    assert nodos.fallo(ticket(tmp_path, pasos=[p], fallo=ERROR))["pasos"][0]["repeticiones"] == 0

    p = paso(huella="h", huella_anterior="h", feedback=[ERROR], ultimo_error=normalizar_error(ERROR))
    upd = nodos.fallo(ticket(tmp_path, pasos=[p], fallo="AssertionError: 4 != 5"))
    assert upd["pasos"][0]["repeticiones"] == 0


# ---------- recortar ----------

def test_recortar_conserva_principio_y_final():
    salida = "PRIMER ERROR\n" + "x" * 10_000 + "\nRESUMEN FINAL"
    r = recortar(salida, limite=1000)
    assert r.startswith("PRIMER ERROR") and r.endswith("RESUMEN FINAL")
    assert "caracteres omitidos" in r and len(r) < 1100
    assert recortar("corto", limite=1000) == "corto"


# ---------- diagnóstico ----------

def test_fallo_pide_diagnostico_una_vez_por_error_repetido(tmp_path):
    nodos = Nodos(config(intentos=10), RouterFalso(""))
    p = paso(huella="a")
    upd = nodos.fallo(ticket(tmp_path, pasos=[p], fallo=ERROR))
    assert not upd["diagnosticar"]  # primera vez que aparece el error

    p = upd["pasos"][0]
    p["huella"] = "b"  # el código cambió, pero el error es el mismo
    upd = nodos.fallo(ticket(tmp_path, pasos=[p], fallo=ERROR))
    assert upd["diagnosticar"]

    p = upd["pasos"][0]
    p["huella"] = "c"
    assert not nodos.fallo(ticket(tmp_path, pasos=[p], fallo=ERROR))["diagnosticar"]  # ya diagnosticado


def test_fallo_no_diagnostica_peticiones_del_revisor(tmp_path):
    cambios = "El revisor pidió cambios:\nfalta un test"
    p = paso(feedback=[cambios], ultimo_error=normalizar_error(cambios))
    upd = Nodos(config(), RouterFalso("")).fallo(ticket(tmp_path, pasos=[p], fallo=cambios))
    assert not upd["diagnosticar"]


def test_diagnostico_antepone_causa_y_accion_al_feedback(tmp_path):
    router = RouterFalso('{"causa": "tests/ es otro crate", "accion": "usa demo::calc"}')
    p = paso(feedback=["intento 1", ERROR])
    upd = Nodos(config(), router).diagnostico(ticket(tmp_path, pasos=[p], fallo=ERROR))

    fb = upd["pasos"][0]["feedback"]
    assert fb[0] == "intento 1"
    assert fb[-1].startswith("DIAGNÓSTICO (causa raíz): tests/ es otro crate\nQUÉ HACER: usa demo::calc")
    assert fb[-1].endswith(ERROR)
    assert "ERROR (repetido):" in router.mensajes[0][1]["content"]
    assert upd["diagnosticar"] is False


class RouterSinModelos:
    def llamar(self, *a, **k):
        raise SinModelos("nada")


def test_diagnostico_sin_modelo_no_rompe_el_ticket(tmp_path):
    p = paso(feedback=[ERROR])
    upd = Nodos(config(), RouterSinModelos()).diagnostico(ticket(tmp_path, pasos=[p], fallo=ERROR))
    assert upd["diagnosticar"] is False and "pasos" not in upd and "error" not in upd
