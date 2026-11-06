"""Explorador do olist.duckdb no navegador (extensão ui do DuckDB).

Executar com:  uv run python ui.py

U1. O que faz
    Abre o olist.duckdb da raiz do projeto, executa INSTALL ui; LOAD ui; e
    CALL start_ui(), que sobe o servidor em http://localhost:4213 e abre o navegador.
U2. Fica de pé até Ctrl+C
    A extensão só serve enquanto a conexão estiver viva, então o processo fica
    rodando, imprime a URL e "Ctrl+C para encerrar"; no Ctrl+C fecha a conexão e
    sai sem traceback. Motivo: o .duckdb aceita um único processo escrevendo; com
    este script de pé a ingestão falha com "Could not set lock on file". Saber
    desligar o servidor faz parte da ferramenta.
U3. Não cria banco
    Se olist.duckdb não existir, avisa que é preciso rodar a ingestão e encerra
    com sys.exit(1). Por isso não usa pipeline.db.conectar(), que criaria o
    arquivo: um banco vazio no navegador pareceria ingestão quebrada.
U4. Separação
    Não importa pipeline/ingestao.py (nem pipeline.db, ver U3), e a ingestão não
    importa este arquivo: a ingestão não sobe servidor nem depende da extensão ui.
U5. Saída
    stdout reconfigurado para utf-8 (acentos no Prompt de Comando do Windows).
"""

import sys
import time
from pathlib import Path

import duckdb

ARQUIVO_DB = Path(__file__).resolve().parent / "olist.duckdb"
URL = "http://localhost:4213"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")

    if not ARQUIVO_DB.is_file():
        print(f"{ARQUIVO_DB} não existe. Rode a ingestão antes: uv run python -m pipeline.ingestao")
        sys.exit(1)

    con = duckdb.connect(str(ARQUIVO_DB))
    try:
        con.execute("INSTALL ui")
        con.execute("LOAD ui")
        con.execute("CALL start_ui()")
        print(f"Servidor de pé em {URL}")
        print("Ctrl+C para encerrar")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        con.close()
        print("Encerrado.")


if __name__ == "__main__":
    main()
