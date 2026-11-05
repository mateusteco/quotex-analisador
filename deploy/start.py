"""Supervisor for the dashboard and its independent continuous worker."""
import os
import signal
import subprocess
import sys
import time

children=[]
def stop(*_):
    for child in children:
        child.terminate()
    for child in children:
        try: child.wait(timeout=10)
        except subprocess.TimeoutExpired: child.kill()
    raise SystemExit(0)
signal.signal(signal.SIGTERM,stop)
signal.signal(signal.SIGINT,stop)
children.append(subprocess.Popen([sys.executable,'futures_worker.py']))
children.append(subprocess.Popen([sys.executable,'-m','streamlit','run','app.py','--server.address=0.0.0.0','--server.port='+os.environ.get('PORT','8501'),'--server.headless=true','--browser.gatherUsageStats=false']))
while True:
    if any(p.poll() is not None for p in children):
        for p in children:
            if p.poll() is None:p.terminate()
        raise SystemExit(1)
    time.sleep(2)
