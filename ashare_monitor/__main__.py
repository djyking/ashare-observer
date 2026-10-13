import argparse
import signal
from pathlib import Path
import threading

from .runtime import Runtime
from .server import DashboardServer


def main():
    parser = argparse.ArgumentParser(description="A 股量化交易研究平台")
    parser.add_argument("--port", type=int, default=18766)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[1] / "var")
    args = parser.parse_args()
    runtime = Runtime(args.data_dir)
    server = DashboardServer(("127.0.0.1", args.port), runtime)
    runtime.start()

    def stop(*_args):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop)
    print(f"A 股量化交易研究平台：http://127.0.0.1:{server.server_address[1]}", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        runtime.close()


if __name__ == "__main__":
    main()
