# -*- coding: utf-8 -*-
"""Janela nativa menor (~360x600) sempre à frente."""
import subprocess
import sys
import time

try:
    import webview
except ImportError:
    raise SystemExit("Instale pywebview: pip install pywebview")

# Ajuste o nome do arquivo do app Streamlit se necessário (ex.: app.py)
STREAMLIT_CMD = [sys.executable, '-m', 'streamlit', 'run', 'app.py',
                 '--server.port', '8501', '--server.headless', 'true']

if __name__ == '__main__':
    proc = subprocess.Popen(STREAMLIT_CMD)
    # Aguarda o servidor subir
    time.sleep(3)
    try:
        # Janela compacta, sempre no topo
        window = webview.create_window(
            'Ponto',
            'http://localhost:8501',
            width=360, height=600,
            topmost=True,
            resizable=True
        )
        webview.start()
    finally:
        # Encerra o Streamlit ao fechar a janela
        proc.terminate()
