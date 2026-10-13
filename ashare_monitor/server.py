"""Loopback-only dashboard, strict origin validation, bounded JSON mutations."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
import json
import secrets

from .runtime import BusyError
from .storage import encode

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
        self.token = secrets.token_urlsafe(32)
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = "AShareDashboard/1.0"

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
            if url.path == "/api/state":
                return self._send(200, self.server.runtime.snapshot(self.server.token))
            if url.path == "/api/health":
                return self._send(200, {"application": "ashare-observer", "status": "ok"})
            if url.path == "/api/history":
                query = parse_qs(url.query)
                return self._send(200, self.server.runtime.store.history(
                    int(query.get("page", [1])[0]), int(query.get("page_size", [30])[0])))
            resources = {"/": ("index.html", "text/html; charset=utf-8"),
                         "/index.html": ("index.html", "text/html; charset=utf-8"),
                         "/app.css": ("app.css", "text/css; charset=utf-8"),
                         "/app.js": ("app.js", "text/javascript; charset=utf-8")}
            if url.path in resources:
                filename, mime = resources[url.path]
                return self._send(200, (WEB / filename).read_bytes(), mime)
            return self._send(404, {"error": "页面或接口不存在。"})
        except (ValueError, TypeError):
            return self._send(400, {"error": "请求参数无效。"})
        except Exception:
            return self._send(500, {"error": "读取失败，请查看应用状态或重新启动。"})

    def do_POST(self):
        if not self._allowed_host():
            return self._send(403, {"error": "请求主机不受支持。"})
        host = self.headers.get("Host", "")
        if self.headers.get("Origin") not in {None, f"http://{host}"}:
            return self._send(403, {"error": "不接受跨站操作。"})
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            return self._send(403, {"error": "不接受跨站操作。"})
        supplied = self.headers.get("X-CSRF-Token", "")
        if not secrets.compare_digest(supplied, self.server.token):
            return self._send(403, {"error": "页面会话已更新，请刷新后重试。"})
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self._send(415, {"error": "需要 JSON 请求。"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 2 <= length <= 16384 or self.headers.get("Transfer-Encoding"):
                raise ValueError("请求体大小无效。")
            self.connection.settimeout(10)
            payload = json.loads(self.rfile.read(length), object_pairs_hook=unique_object,
                                 parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("非法数值")))
            if not isinstance(payload, dict):
                raise ValueError("请求体需要对象。")
            path = urlsplit(self.path).path
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
            return self._send(404, {"error": "操作不存在。"})
        except BusyError as exc:
            return self._send(409, {"error": str(exc)})
        except (ValueError, TypeError, KeyError) as exc:
            return self._send(400, {"error": str(exc)[:240]})
        except Exception:
            return self._send(500, {"error": "操作未完成，已保留先前账本。"})
