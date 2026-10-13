"""Start the local dashboard without a visible long-running console."""
from pathlib import Path
import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
URL = "http://127.0.0.1:18766"


def healthy():
    try:
        with urllib.request.urlopen(URL + "/api/health", timeout=1) as response:
            return json.load(response).get("application") == "ashare-observer"
    except Exception:
        return False


def main():
    if not healthy():
        state_dir = ROOT / "var"
        state_dir.mkdir(exist_ok=True)
        log_path = state_dir / "launcher.log"
        with log_path.open("ab") as log:
            child = subprocess.Popen([sys.executable, "-m", "ashare_monitor", "--port", "18766"],
                                     cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        for _ in range(40):
            if healthy():
                break
            if child.poll() is not None:
                print(f"启动失败，请查看：{log_path}")
                return 1
            time.sleep(0.25)
        else:
            print(f"服务启动超时，请查看：{log_path}")
            return 1
    if "--no-browser" not in sys.argv:
        webbrowser.open(URL)
    print(f"A 股量化交易研究平台：{URL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
