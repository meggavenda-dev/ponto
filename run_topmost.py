
# -*- coding: utf-8 -*-
"""Janela nativa menor (~360x600) sempre à frente."""
import subprocess
import sys
import time
try:
    import webview
except ImportError:
    raise SystemExit("Instale pywebview: pip install pywebview")

STREAMLIT_CMD = [sys.executable, '-m', 'streamlit', 'run', 'app.py',
                 '--server.port', '8501', '--server.headless', 'true']

if __name__ == '__main__':
    proc = subprocess.Popen(STREAMLIT_CMD)
    time.sleep(3)
    try:
        # Janela compacta
        window = webview.create_window(
            'Ponto',
            'http://localhost:8501',
            width=360, height=600,  # 👈 menor
            topmost=True,
            resizable=True
        )
        webview.start()
    finally:
        proc.terminate()
