"""HTTP 入口：stdlib http.server + 自定义 Router，集成审计 + JSONL 日志。

启动：  py -m web.server --host 127.0.0.1 --port 8787
"""

from __future__ import annotations

import argparse
import json
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from shared import errors
from shared.result import Result
from shared.result import ResultError
from web import response
from web.router import Router

API_VERSION = "2.0.0"
_STARTED_AT = time.time()


def build_router() -> Router:
    r = Router()
    r.get("/api/health", lambda **_: Result.success(
        {"status": "ok", "version": API_VERSION, "uptime_s": int(time.time() - _STARTED_AT)}))
    from api import companies, sites, inventory, addon_studio, deliveries, config
    companies.register(r); sites.register(r); inventory.register(r)
    addon_studio.register(r); deliveries.register(r); config.register(r)
    return r


def _make_handler(audit_repo, log_writer, router):
    """闭包注入 audit/log/router——最可靠的方式。"""

    class Handler(BaseHTTPRequestHandler):
        server_version = "AiConfigTool/" + API_VERSION

        def _dispatch(self, method):
            started = time.monotonic()
            rid = "req_%d" % int(started * 1000)
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            body = None
            params = {}
            status_code = 200
            error_code = None

            try:
                match = router.match(method, path)
                if match is None:
                    code = 404 if not router.path_exists(path) else 405
                    err_code = "NOT_FOUND" if code == 404 else "VALIDATION_ERROR"
                    body_payload = response.error_body(ResultError(err_code, "资源不存在" if code == 404 else "方法不被允许"), rid, started)
                    self._json(code, body_payload)
                    status_code, error_code = code, err_code
                    return
                handler, params = match
                body = self._read_body()

                result = handler(params=params, query=query, body=body)
                if not isinstance(result, Result):
                    result = Result.success(result)

                if result.is_success() and isinstance(result.value, dict) and "__file__" in result.value:
                    self._file(result.value["__file__"], result.value.get("filename"))
                    return

                status_code = 200 if result.is_success() else errors.http_status_for(result.error.code)
                if result.is_failure():
                    error_code = result.error.code
                self._json(status_code, response.body_from_result(result, rid, started))

            except Exception as exc:
                status_code, error_code = 500, errors.INTERNAL_ERROR
                tb = traceback.format_exc()
                self._json(500, response.error_body(ResultError(errors.INTERNAL_ERROR, "内部错误: %s" % exc), rid, started))
                if log_writer:
                    log_writer.error("server", "内部错误 %s" % exc, path=path, method=method, request_id=rid, traceback=tb)

            finally:
                elapsed = int((time.monotonic() - started) * 1000)
                if log_writer:
                    log_writer.write("server", "ERROR" if status_code >= 400 else "INFO",
                                     "%s %s -> %d" % (method, path, status_code),
                                     step="http", request_id=rid, method=method, path=path,
                                     status=status_code, error_code=error_code, elapsed_ms=elapsed)
                if audit_repo and path != "/api/health":
                    try:
                        body_snip = None
                        if isinstance(body, dict):
                            body_snip = {k: (str(v)[:120] if isinstance(v, str) and len(str(v)) > 120 else v) for k, v in body.items()}
                        audit_repo.log_operation(
                            session_id="http", op_type=method,
                            site_code=params.get("code") if params else None,
                            params=body_snip,
                            result="failed" if status_code >= 400 else "success",
                            run_id=rid, error_code=error_code, duration_ms=elapsed)
                    except Exception as ex:
                        if log_writer:
                            log_writer.error("server", "审计写入失败: " + str(ex))

        def do_GET(self): self._dispatch("GET")
        def do_POST(self): self._dispatch("POST")
        def do_PUT(self): self._dispatch("PUT")
        def do_DELETE(self): self._dispatch("DELETE")

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def _read_body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0: return None
            try: return json.loads(self.rfile.read(n).decode("utf-8"))
            except (ValueError, UnicodeDecodeError): return None

        def _json(self, status, data):
            raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
            self.wfile.write(raw)

        def _file(self, path, filename):
            with open(path, "rb") as h: data = h.read()
            ct = "application/zip"
            disp = 'attachment'
            if filename and filename.endswith(".md"):
                ct = "text/plain; charset=utf-8"
                disp = 'inline'
            if filename and filename.endswith(".txt"):
                ct = "text/plain; charset=utf-8"
                disp = 'inline'
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Disposition", '%s; filename="%s"' % (disp, filename or "download.zip"))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt, *args):
            if log_writer:
                log_writer.info("server", fmt % args if args else fmt)

    return Handler


def main():
    parser = argparse.ArgumentParser(description="AiConfigTool backend server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    from infrastructure.audit_repository import AuditRepository
    from infrastructure.log_writer import LogWriter
    router = build_router()
    audit = AuditRepository()
    log = LogWriter()
    log.info("server", "启动 AiConfigTool v" + API_VERSION)
    log.cleanup()

    Handler = _make_handler(audit, log, router)
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print("AiConfigTool backend on http://%s:%d" % (args.host, args.port))
    print("  SQLite: data/audit.db")
    print("  Logs:   data/logs/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("server", "关闭")
        print("\nshutting down")
        httpd.shutdown()


if __name__ == "__main__":
    main()
