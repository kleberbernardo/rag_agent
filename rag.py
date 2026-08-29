"""Atalho para rodar a CLI sem instalar o pacote. Uso: python rag.py ask "..." """

import sys
from pathlib import Path

# Coloca a pasta src/ no caminho de importação do Python
sys.path.insert(0, str(Path(__file__).parent / "src"))
# Garante acentos corretos no console do Windows
sys.stdout.reconfigure(encoding="utf-8")

from rag_agent.cli import app

app()
