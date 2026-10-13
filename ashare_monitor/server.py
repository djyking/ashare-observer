"""Loopback-only dashboard, strict origin validation, bounded JSON mutations."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, unquote
import json
import secrets

from .runtime import BusyError
from .brokers import BrokerGateway, BrokerError
from .storage import encode
from .strategies import strategy_catalog
from .market_tools import search_securities, watchlist_templates, csv_template

WEB = Path(__file__).parent / "web"


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("重复 JSON 字段")
        obj[key] = value
    return obj


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, runtime):
        if address[0] != "127.0.0.1":
            raise ValueError("看板仅支持本机回环地址。")
        self.runtime = runtime
        self.brokers = BrokerGateway(runtime)
        self.token = secrets.token_urlsafe(32)
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = "AShareDashboard/1.2"

    def log_message(self, _fmt, *_args):
        # No posted account-like information or arbitrary query text in logs.
        pass

    def _allowed_host(self):
        port = self.server.server_address[1]
        return self.headers.get("Host", "").lower() in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _send(self, status, data, content_type="application/json; charset=utf-8"):
        body = data if isinstance(data, bytes) else encode(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if not self._allowed_host():
            return self._send(403, {"error": "请求主机不受支持。"})
        url = urlsplit(self.path)
        try:
            query = parse_qs(url.query)
            parts = url.path.strip("/").split("/")
            runtime = self.server.runtime
            if url.path == "/api/state":
                return self._send(200, runtime.snapshot(self.server.token, compact=True))
            if url.path == "/api/health":
                return self._send(200, {"application": "ashare-observer", "status": "ok"})
            if url.path == "/api/history":
                return self._send(200, runtime.store.history(
                    int(query.get("page", [1])[0]), int(query.get("page_size", [30])[0])))
            if len(parts) == 3 and parts[:2] == ["api", "history"]:
                return self._send(200, runtime.store.history_detail(parts[2]))
            if url.path == "/api/strategies":
                return self._send(200, strategy_catalog())
            if url.path == "/api/stocks/search":
                return self._send(200, search_securities(query.get("q", [""])[0]))
            if url.path == "/api/stocks/templates":
                return self._send(200, {"items": watchlist_templates()})
            if url.path == "/api/imports/template":
                return self._send(200, csv_template().encode("utf-8-sig"), "text/csv; charset=utf-8")
            if url.path == "/api/paper/records":
                return self._send(200, runtime.paper_records(query.get("kind", ["orders"])[0], query.get("page", [1])[0]))
            if url.path in {"/api/research", "/api/demo/experiments"}:
                kind = "research" if url.path == "/api/research" else "demo"
                return self._send(200, runtime.store.experiments(kind, query.get("page", [1])[0]))
            if len(parts) == 3 and parts[:2] == ["api", "research"]:
                return self._send(200, runtime.research_detail(parts[2]))
            if len(parts) == 4 and parts[:3] == ["api", "demo", "experiments"]:
                return self._send(200, runtime.store.experiment(parts[3], "demo"))
            if url.path == "/api/brokers":
                return self._send(200, self.server.brokers.catalog())
            parts = url.path.strip("/").split("/")
            if len(parts) == 4 and parts[:2] == ["api", "brokers"] and parts[3] in {"account", "positions", "orders", "trades"}:
                return self._send(200, getattr(self.server.brokers, parts[3])(parts[2]))
            if url.path in {"/", "/index.html"}:
                index = WEB / "index.html"
                if not index.is_file():
                    return self._send(503, {"error": "前端尚未构建，请在 frontend 中运行 npm ci 和 npm run build。"})
                return self._send(200, index.read_bytes(), "text/html; charset=utf-8")
            # Only serve Vite assets beneath the build directory. Decode before
            # checking segments; resolve also prevents a symlink escape.
            path = unquote(url.path)
            if path.startswith("/assets/") and not any(c in path for c in ("\\", ":", "\x00")):
                segments = path.lstrip("/").split("/")
                mime = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
                        ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
                        ".webp": "image/webp", ".woff2": "font/woff2"}
                if not any(part in {"", ".", ".."} for part in segments):
                    asset = WEB.joinpath(*segments).resolve()
                    if asset.is_relative_to(WEB.resolve()) and asset.is_relative_to((WEB / "assets").resolve()) and asset.suffix in mime and asset.is_file():
                        return self._send(200, asset.read_bytes(), mime[asset.suffix])
            return self._send(404, {"error": "页面或接口不存在。"})
        except BrokerError as exc:
            return self._send(exc.status_code, {"error": exc.public_message, "code": exc.code})
        except KeyError as exc:
            return self._send(404, {"error": str(exc)[:180]})
        except (ValueError, TypeError):
            return self._send(400, {"error": "请求参数无效。"})
        except Exception:
            return self._send(500, {"error": "读取失败，请查看应用状态或重新启动。"})

    def _reject_post(self, status, message):
        # http.client and browsers may send headers and body in separate writes.
        # Consume a small declared body before closing, otherwise Windows may
        # reset the connection and hide the intended 403/415 response.
        self.close_connection = True
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if 0 < length <= 16384 and not self.headers.get("Transfer-Encoding"):
                self.connection.settimeout(1)
                self.rfile.read(length)
        except (ValueError, OSError):
            pass
        return self._send(status, {"error": message})

    def do_POST(self):
        if not self._allowed_host():
            return self._reject_post(403, "请求主机不受支持。")
        host = self.headers.get("Host", "")
        if self.headers.get("Origin") not in {None, f"http://{host}"}:
            return self._reject_post(403, "不接受跨站操作。")
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            return self._reject_post(403, "不接受跨站操作。")
        supplied = self.headers.get("X-CSRF-Token", "")
        if not supplied.isascii() or not secrets.compare_digest(supplied, self.server.token):
            return self._reject_post(403, "页面会话已更新，请刷新后重试。")
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self._reject_post(415, "需要 JSON 请求。")
        try:
            path = urlsplit(self.path).path
            length = int(self.headers.get("Content-Length", "0"))
            maximum = 2_000_000 if path in {"/api/imports/validate", "/api/imports/commit"} else 16384
            if not 2 <= length <= maximum or self.headers.get("Transfer-Encoding"):
                raise ValueError("请求体大小无效。")
            self.connection.settimeout(10)
            payload = json.loads(self.rfile.read(length), object_pairs_hook=unique_object,
                                 parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("非法数值")))
            if not isinstance(payload, dict):
                raise ValueError("请求体需要对象。")
            runtime = self.server.runtime
            if path in {"/api/refresh", "/api/demo/advance"}:
                if payload:
                    raise ValueError("该操作不接受额外参数。")
                return self._send(202, runtime.request_refresh(path.endswith("advance")))
            if path == "/api/settings":
                return self._send(202, runtime.settings(payload))
            if path == "/api/paper/order":
                return self._send(200, runtime.paper_order(payload))
            if path == "/api/paper/cancel":
                return self._send(200, runtime.cancel(payload))
            if path == "/api/paper/preview":
                return self._send(200, runtime.preview_order(payload))
            if path == "/api/demo/experiments":
                return self._send(202, runtime.new_demo_experiment(payload))
            if path in {"/api/imports/validate", "/api/imports/commit"}:
                return self._send(200, runtime.import_csv(payload, commit=path.endswith("commit")))
            if path == "/api/research":
                return self._send(202, runtime.start_research(payload))
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[:2] == ["api", "research"] and parts[3] == "archive":
                if payload:
                    raise ValueError("归档操作不接受额外配置。")
                item = runtime.store.experiment(parts[2], "research")
                if item["status"] == "running":
                    raise BusyError("运行中的实验暂不能归档。")
                runtime.store.update_experiment(parts[2], {"archived": True})
                return self._send(200, {"ok": True, "id": parts[2], "archived": True})
            if len(parts) == 4 and parts[:2] == ["api", "brokers"] and parts[3] in {"orders", "cancel"}:
                operation = "place_order" if parts[3] == "orders" else "cancel_order"
                return self._send(200, getattr(self.server.brokers, operation)(parts[2], payload))
            return self._send(404, {"error": "操作不存在。"})
        except BrokerError as exc:
            return self._send(exc.status_code, {"error": exc.public_message, "code": exc.code})
        except BusyError as exc:
            return self._send(409, {"error": str(exc)})
        except (ValueError, TypeError, KeyError) as exc:
            return self._send(400, {"error": str(exc)[:240]})
        except Exception:
            return self._send(500, {"error": "操作未完成，已保留先前账本。"})
