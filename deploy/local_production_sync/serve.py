"""Windows loopback bridge for the local ERP's one-click production reset."""

import base64
import json
import os
import shlex
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import zlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ORIGINS = {"http://localhost:8080", "http://127.0.0.1:8080"}
PORT = 18724
DOCKER = ["docker", "--host", "npipe:////./pipe/docker_engine"]
SSH_SCRIPT = Path(os.environ.get(
    "HAIQU_LOCAL_SYNC_SSH_SCRIPT", "E:/CodexData/.codex/skills/bushu/scripts/ssh.py"))
RUN_LOCK = threading.Lock()
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class BridgeError(Exception):
    pass


def run(command, *, timeout, error, data=None):
    result = subprocess.run(command, input=data, capture_output=True, cwd=ROOT,
                            creationflags=NO_WINDOW, timeout=timeout)
    if result.returncode:
        if result.returncode == 2 and result.stderr:
            reason = result.stderr.decode("utf-8", errors="replace").strip()
            if len(reason) < 240 and "\n" not in reason:
                raise BridgeError(reason)
        raise BridgeError(error)
    return result.stdout


def transfer():
    project = run([*DOCKER, "inspect", "haiqu-backend", "--format",
                   '{{index .Config.Labels "com.docker.compose.project.working_dir"}}'],
                  timeout=10, error="本地 ERP 后端未启动。")
    if not project.strip() or Path(os.fsdecode(project.strip())).resolve() != ROOT:
        raise BridgeError("本地 ERP 后端不属于当前项目。")
    if not SSH_SCRIPT.is_file():
        raise BridgeError("找不到本机已有的服务器连接工具。")
    code = base64.b64encode(zlib.compress(Path(__file__).with_name("sync_data.py").read_bytes())).decode("ascii")
    python = ["python", "-B", "-c", f"import base64,zlib;exec(zlib.decompress(base64.b64decode({code!r})))"]
    remote = shlex.join(["docker", "exec", "haiqu-erp-server-backend-1", *python, "export"])
    payload = run([sys.executable, "-X", "utf8", "-B", str(SSH_SCRIPT), "--timeout", "150",
                   "run", "--command", remote], timeout=160, error="服务器数据读取失败，本地数据未动。")
    result = run([*DOCKER, "exec", "-i", "haiqu-backend", *python, "replace"], data=payload,
                 timeout=180, error="本地覆盖失败，数据库未提交。")
    return json.loads(result)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def respond(self, status, data=None):
        self.send_response(status)
        origin = self.headers.get("Origin")
        if origin in ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "X-CSRFToken")
            self.send_header("Vary", "Origin")
        self.send_header("Cache-Control", "no-store")
        if data is not None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if data is not None:
            self.wfile.write(body)

    def valid_origin(self):
        return (self.path == "/sync" and self.headers.get("Origin") in ORIGINS
                and self.headers.get("Host") in {f"localhost:{PORT}", f"127.0.0.1:{PORT}"})

    def do_OPTIONS(self):
        self.respond(HTTPStatus.NO_CONTENT if self.valid_origin() else HTTPStatus.FORBIDDEN)

    def permitted(self):
        origin = self.headers.get("Origin")
        cookie = self.headers.get("Cookie")
        token = self.headers.get("X-CSRFToken")
        if not cookie or not token:
            return False
        request = urllib.request.Request(
            "http://127.0.0.1:8000/api/auth/local-production-sync/", method="POST", data=b"",
            headers={"Origin": origin, "Cookie": cookie, "X-CSRFToken": token},
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            with opener.open(request, timeout=8) as response:
                return response.status == HTTPStatus.NO_CONTENT
        except urllib.error.URLError:
            return False

    def do_POST(self):
        if not self.valid_origin() or not self.permitted():
            self.respond(HTTPStatus.FORBIDDEN, {"detail": "请用本机 ERP 管理员账号登录后操作。"})
            return
        if not RUN_LOCK.acquire(blocking=False):
            self.respond(HTTPStatus.CONFLICT, {"detail": "已有一次同步正在执行。"})
            return
        try:
            result = transfer()
        except BridgeError as error:
            self.respond(HTTPStatus.CONFLICT, {"detail": str(error)})
        except (OSError, subprocess.TimeoutExpired, ValueError):
            self.respond(HTTPStatus.SERVICE_UNAVAILABLE, {"detail": "同步中断，请刷新本地页面查看结果。"})
        else:
            self.respond(HTTPStatus.OK, result)
        finally:
            RUN_LOCK.release()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_):
        return None


if __name__ == "__main__":
    with ThreadingHTTPServer(("127.0.0.1", PORT), Handler) as server:
        server.serve_forever()
