"""Testes de pipeline/transformacao.py (spec 1-9 e critérios a-f na docstring).

O módulo vigente trata só raw.geolocalizacao -> refined.geolocalizacao.
Todas as linhas de entrada são inventadas pelo teste.
"""

import io
import sys

import duckdb
import pytest

from pipeline import db, refinar_tabelas, transformacao

COLUNAS = [
    "geolocation_zip_code_prefix",
    "geolocation_lat",
    "geolocation_lng",
    "geolocation_city",
    "geolocation_state",
]


@pytest.fixture(autouse=True)
def _sem_as_outras_oito_tabelas(monkeypatch):
    """Estes testes cobrem só a geolocalizacao; as outras oito têm test_refinar_tabelas.py."""
    monkeypatch.setattr(refinar_tabelas, "executar", lambda con: None)


def preparar(tmp_path, monkeypatch, linhas):
    """Banco novo em tmp_path com raw.geolocalizacao (tudo VARCHAR) com as linhas dadas."""
    banco = tmp_path / "teste.duckdb"
    monkeypatch.setattr(db, "_ARQUIVO_DB", banco)
    con = duckdb.connect(str(banco))
    try:
        con.execute("CREATE SCHEMA raw")
        con.execute(
            "CREATE TABLE raw.geolocalizacao ("
            + ", ".join(f'"{c}" VARCHAR' for c in COLUNAS)
            + ")"
        )
        con.executemany("INSERT INTO raw.geolocalizacao VALUES (?, ?, ?, ?, ?)", linhas)
    finally:
        con.close()
    return banco


def consultar(banco, sql):
    con = duckdb.connect(str(banco))
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def capturar_saida(monkeypatch):
    buf = io.BytesIO()
    texto = io.TextIOWrapper(buf, encoding="utf-8", newline="\n", write_through=True)
    monkeypatch.setattr(sys, "stdout", texto)
    return lambda: buf.getvalue().decode("utf-8")


# Linhas-base: duas linhas distintas
A = ("01037", "-23.5", "-46.6", "sao paulo", "SP")
B = ("20000", "-22.9", "-43.2", "rio de janeiro", "RJ")


def test_formatar_usa_ponto_como_separador_de_milhar():
    assert transformacao.formatar(1234567) == "1.234.567"
    assert transformacao.formatar(12) == "12"


def test_refined_tem_as_cinco_colunas_com_os_nomes_e_a_ordem_de_raw(tmp_path, monkeypatch):
    banco = preparar(tmp_path, monkeypatch, [A])
    transformacao.main()
    colunas = [
        r[0]
        for r in consultar(
            banco,
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'refined' AND table_name = 'geolocalizacao' "
            "ORDER BY ordinal_position",
        )
    ]
    assert colunas == COLUNAS


def test_lat_e_lng_viram_double_e_as_demais_continuam_varchar(tmp_path, monkeypatch):
    banco = preparar(tmp_path, monkeypatch, [A])
    transformacao.main()
    tipos = dict(
        consultar(
            banco,
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'refined' AND table_name = 'geolocalizacao'",
        )
    )
    assert tipos == {
        "geolocation_zip_code_prefix": "VARCHAR",
        "geolocation_lat": "DOUBLE",
        "geolocation_lng": "DOUBLE",
        "geolocation_city": "VARCHAR",
        "geolocation_state": "VARCHAR",
    }


def test_coordenada_e_convertida_para_o_numero_do_texto(tmp_path, monkeypatch):
    banco = preparar(tmp_path, monkeypatch, [A])
    transformacao.main()
    linha = consultar(banco, "SELECT geolocation_lat, geolocation_lng FROM refined.geolocalizacao")
    assert linha == [(-23.5, -46.6)]


def test_duplicata_exata_sai_e_fica_uma_copia(tmp_path, monkeypatch):
    # A aparece três vezes idêntica; B uma vez
    banco = preparar(tmp_path, monkeypatch, [A, A, A, B])
    transformacao.main()
    assert consultar(banco, "SELECT count(*) FROM refined.geolocalizacao") == [(2,)]
    assert consultar(
        banco, "SELECT count(*) FROM refined.geolocalizacao WHERE geolocation_state = 'SP'"
    ) == [(1,)]


def test_mesmo_cep_com_coordenada_diferente_nao_e_duplicata(tmp_path, monkeypatch):
    # mesmo CEP, lat diferente: o CEP se repete por desenho do dataset
    outra = ("01037", "-23.6", "-46.6", "sao paulo", "SP")
    banco = preparar(tmp_path, monkeypatch, [A, outra])
    transformacao.main()
    assert consultar(banco, "SELECT count(*) FROM refined.geolocalizacao") == [(2,)]


def test_mesmo_cep_com_cidade_diferente_nao_e_duplicata(tmp_path, monkeypatch):
    # mesmo CEP e mesmas coordenadas, cidade escrita de outro jeito
    outra = ("01037", "-23.5", "-46.6", "são paulo", "SP")
    banco = preparar(tmp_path, monkeypatch, [A, outra])
    transformacao.main()
    assert consultar(banco, "SELECT count(*) FROM refined.geolocalizacao") == [(2,)]


def test_duplicata_e_decidida_pelo_texto_de_raw_antes_da_conversao(tmp_path, monkeypatch):
    # "-23.5" e "-23.50" são o mesmo número, mas textos diferentes em raw: ficam as duas
    mesmo_numero = ("01037", "-23.50", "-46.6", "sao paulo", "SP")
    banco = preparar(tmp_path, monkeypatch, [A, mesmo_numero])
    transformacao.main()
    assert consultar(banco, "SELECT count(*) FROM refined.geolocalizacao") == [(2,)]


def test_cep_com_zero_a_esquerda_continua_com_cinco_caracteres(tmp_path, monkeypatch):
    banco = preparar(tmp_path, monkeypatch, [A])
    transformacao.main()
    assert consultar(banco, "SELECT geolocation_zip_code_prefix FROM refined.geolocalizacao") == [
        ("01037",)
    ]


def test_nulo_continua_nulo_e_a_linha_com_nulo_nao_e_descartada(tmp_path, monkeypatch):
    # cidade nula e lat nula na mesma linha
    com_nulos = ("30000", None, "-43.9", None, "MG")
    banco = preparar(tmp_path, monkeypatch, [A, com_nulos])
    transformacao.main()
    linha = consultar(
        banco,
        "SELECT geolocation_lat IS NULL, geolocation_city IS NULL, geolocation_lng "
        "FROM refined.geolocalizacao WHERE geolocation_zip_code_prefix = '30000'",
    )
    assert linha == [(True, True, -43.9)]
    assert consultar(banco, "SELECT count(*) FROM refined.geolocalizacao") == [(2,)]


def test_lat_que_nao_converte_encerra_com_systemexit_dizendo_tabela_e_coluna(tmp_path, monkeypatch):
    estragada = ("40000", "abc", "-43.9", "salvador", "BA")
    preparar(tmp_path, monkeypatch, [A, estragada])
    saida = capturar_saida(monkeypatch)
    with pytest.raises(SystemExit) as erro:
        transformacao.main()
    texto = saida()
    assert erro.value.code == 1
    assert "geolocation_lat" in texto
    assert "raw.geolocalizacao" in texto


def test_lng_que_nao_converte_encerra_com_systemexit_dizendo_a_coluna(tmp_path, monkeypatch):
    estragada = ("40000", "-12.9", "xyz", "salvador", "BA")
    preparar(tmp_path, monkeypatch, [A, estragada])
    saida = capturar_saida(monkeypatch)
    with pytest.raises(SystemExit) as erro:
        transformacao.main()
    texto = saida()
    assert erro.value.code == 1
    assert "geolocation_lng" in texto


def test_valor_que_nao_converte_nao_vira_nulo_nem_cria_a_tabela(tmp_path, monkeypatch):
    estragada = ("40000", "abc", "-43.9", "salvador", "BA")
    banco = preparar(tmp_path, monkeypatch, [A, estragada])
    with pytest.raises(SystemExit):
        transformacao.main()
    existe = consultar(
        banco,
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = 'refined' AND table_name = 'geolocalizacao'",
    )
    assert existe == [(0,)]


def test_raw_nao_muda_depois_da_execucao(tmp_path, monkeypatch):
    banco = preparar(tmp_path, monkeypatch, [A, A, B])
    antes = consultar(banco, "SELECT * FROM raw.geolocalizacao ORDER BY ALL")
    transformacao.main()
    depois = consultar(banco, "SELECT * FROM raw.geolocalizacao ORDER BY ALL")
    assert depois == antes
    assert len(depois) == 3


def test_diferenca_entre_raw_e_refined_e_o_numero_de_duplicatas_informado(tmp_path, monkeypatch):
    # 4 linhas em raw, 3 idênticas -> 2 duplicatas removidas
    banco = preparar(tmp_path, monkeypatch, [A, A, A, B])
    saida = capturar_saida(monkeypatch)
    transformacao.main()
    texto = saida()
    raw = consultar(banco, "SELECT count(*) FROM raw.geolocalizacao")[0][0]
    refined = consultar(banco, "SELECT count(*) FROM refined.geolocalizacao")[0][0]
    assert raw - refined == 2
    assert "raw.geolocalizacao: 4 linhas lidas" in texto
    assert "refined.geolocalizacao: 2 linhas gravadas" in texto
    assert "2 linhas removidas por duplicata" in texto


def test_saida_diz_que_nenhuma_linha_foi_removida_quando_nao_ha_duplicata(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch, [A, B])
    saida = capturar_saida(monkeypatch)
    transformacao.main()
    texto = saida()
    assert "nenhuma linha removida" in texto
    assert "removidas por duplicata" not in texto


def test_saida_lista_as_colunas_com_nulo_e_a_contagem(tmp_path, monkeypatch):
    # duas linhas com cidade nula, uma com lat nula
    linhas = [
        A,
        ("30000", None, "-43.9", None, "MG"),
        ("50000", "-8.0", "-34.9", None, "PE"),
    ]
    preparar(tmp_path, monkeypatch, linhas)
    saida = capturar_saida(monkeypatch)
    transformacao.main()
    texto = saida()
    assert "nulos mantidos: geolocation_lat 1, geolocation_city 2" in texto


def test_saida_nao_cita_nulos_quando_nao_ha(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch, [A, B])
    saida = capturar_saida(monkeypatch)
    transformacao.main()
    assert "nulos mantidos" not in saida()


def test_segunda_execucao_imprime_as_mesmas_contagens_e_nao_acrescenta(tmp_path, monkeypatch):
    banco = preparar(tmp_path, monkeypatch, [A, A, B])
    saida = capturar_saida(monkeypatch)
    transformacao.main()
    primeira = saida()
    saida_2 = capturar_saida(monkeypatch)
    transformacao.main()
    assert saida_2() == primeira
    assert consultar(banco, "SELECT count(*) FROM refined.geolocalizacao") == [(2,)]


def test_sem_raw_geolocalizacao_manda_rodar_a_ingestao_e_encerra(tmp_path, monkeypatch):
    banco = tmp_path / "vazio.duckdb"
    monkeypatch.setattr(db, "_ARQUIVO_DB", banco)
    saida = capturar_saida(monkeypatch)
    with pytest.raises(SystemExit) as erro:
        transformacao.main()
    texto = saida()
    assert erro.value.code == 1
    assert "raw.geolocalizacao" in texto
    assert "uv run python -m pipeline.ingestao" in texto
