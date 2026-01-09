
# -*- coding: utf-8 -*-
"""Wrapper Windows para manter a janela do app sempre à frente usando pywebview."""
import subprocess
import sys
import time
try:
    import webview
except ImportError:
    raise SystemExit("pywebview não instalado. Execute: pip install pywebview")

STREAMLIT_CMD = [sys.executable, '-m', 'streamlit', 'run', 'app.py', '--server.port', '8501', '--server.headless', 'true']

if __name__ == '__main__':
    proc = subprocess.Popen(STREAMLIT_CMD)
    time.sleep(3)
    try:
        window = webview.create_window('Registro de Ponto', 'http://localhost:8501', width=420, height=720, topmost=True, resizable=True)
        webview.start()
    finally:
        proc.terminate()
