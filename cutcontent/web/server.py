"""The local web interface: ``cutcontent gui``.

Safety rules of this server:

- It listens on 127.0.0.1 only and rejects requests whose ``Host`` header is not
  ``127.0.0.1:<port>`` or ``localhost:<port>`` (protection against DNS rebinding).
- Every API call needs the random session token that is embedded in the page.
  Other web sites cannot read the page, so they cannot call the API.
- Scans and previews are limited to the allowed folders (see ``core/folders.py``).
  The interface cannot add folders; that is done with ``cutcontent folders add``.
- Game files are only opened for reading.
"""

from __future__ import annotations

import json
import mimetypes
import secrets
import threading
import time
import traceback
import uuid
from collections import OrderedDict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from cutcontent.core import service
from cutcontent.core.game_launch import GameLaunch, prepare_game_launch
from cutcontent.core.native_gameplay import NativeGameManager, native_build_status
from cutcontent.core.folders import FolderPermissionError
from cutcontent.core.scan_report import load_report
from cutcontent.core.settings import data_directory
from cutcontent.platforms.base import PreviewError

STATIC_DIRECTORY = Path(__file__).resolve().parent / "static"
LISTEN_ADDRESS = "127.0.0.1"
PREVIEW_CACHE_BYTES = 96 * 1024 * 1024
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
)
ENGINE_CONTENT_SECURITY_POLICY = CONTENT_SECURITY_POLICY.replace("script-src 'self'", "script-src 'self' 'wasm-unsafe-eval'").replace("frame-ancestors 'none'", "frame-ancestors 'self'")


class PreviewCache:
    """Keeps recently built previews in memory (3D levels take a moment to convert)."""

    def __init__(self, byte_limit: int):
        self.byte_limit = byte_limit
        self.entries: OrderedDict[str, tuple[str, bytes]] = OrderedDict()
        self.lock = threading.Lock()

    def get(self, key: str):
        with self.lock:
            entry = self.entries.get(key)
            if entry is not None:
                self.entries.move_to_end(key)
            return entry

    def put(self, key: str, value: tuple[str, bytes]) -> None:
        with self.lock:
            self.entries[key] = value
            self.entries.move_to_end(key)
            while sum(len(body) for _, body in self.entries.values()) > self.byte_limit and len(self.entries) > 1:
                self.entries.popitem(last=False)

    def forget_build(self, build_id: str) -> None:
        with self.lock:
            for key in [key for key in self.entries if key.startswith(build_id + "/")]:
                del self.entries[key]


class ApplicationState:
    def __init__(self, port: int):
        self.port = port
        self.token = secrets.token_urlsafe(24)
        self.jobs: dict[str, dict] = {}
        self.scan_lock = threading.Lock()
        self.preview_cache = PreviewCache(PREVIEW_CACHE_BYTES)
        self.game_sessions: dict[str, GameLaunch] = {}
        self.allow_unverified_engine = False  # enabled only by the local engine acceptance test
        self.native_games = NativeGameManager()

    def allowed_hosts(self) -> set[str]:
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

    def start_scan(self, path: str) -> str:
        job_id = uuid.uuid4().hex[:12]
        job = {"id": job_id, "status": "waiting", "path": path, "started": time.time()}
        self.jobs[job_id] = job

        def run() -> None:
            with self.scan_lock:  # one scan at a time keeps small machines responsive
                job["status"] = "running"
                try:
                    report = service.scan_build_in_allowed_folder(path)
                    self.preview_cache.forget_build(report.build_id)
                    job.update(status="done", build_id=report.build_id, statistics=report.statistics())
                except FolderPermissionError as error:
                    job.update(status="failed", error=str(error))
                except Exception as error:  # reported to the interface
                    job.update(status="failed", error=f"{type(error).__name__}: {error}")
                    traceback.print_exc()
                job["finished"] = time.time()

        threading.Thread(target=run, name=f"scan-{job_id}", daemon=True).start()
        return job_id


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "CutContentAnything"
    state: ApplicationState  # set by make_server

    def log_message(self, format_text: str, *arguments) -> None:  # keep the terminal quiet
        pass

    # ----------------------------------------------------------- responses
    def _common_headers(self) -> None:
        self.send_header("Content-Security-Policy", ENGINE_CONTENT_SECURITY_POLICY if getattr(self, "engine_response", False) else CONTENT_SECURITY_POLICY)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._common_headers()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, payload, status: int = 200) -> None:
        self._send(status, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def _send_error_json(self, status: int, message: str) -> None:
        self._send_json({"error": message}, status)

    def _send_body_with_ranges(self, content_type: str, body: bytes) -> None:
        """Audio elements ask for byte ranges; answering them makes seeking work."""
        range_header = self.headers.get("Range", "")
        if range_header.startswith("bytes=") and "," not in range_header:
            start_text, _, end_text = range_header[6:].partition("-")
            try:
                start = int(start_text) if start_text else max(0, len(body) - int(end_text))
                end = int(end_text) if end_text and start_text else len(body) - 1
            except ValueError:
                start, end = 0, len(body) - 1
            end = min(end, len(body) - 1)
            if 0 <= start <= end:
                chunk = body[start : end + 1]
                self.send_response(HTTPStatus.PARTIAL_CONTENT)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(body)}")
                self.send_header("Content-Length", str(len(chunk)))
                self.send_header("Accept-Ranges", "bytes")
                self._common_headers()
                self.end_headers()
                self.wfile.write(chunk)
                return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Accept-Ranges", "bytes")
        self._common_headers()
        self.end_headers()
        self.wfile.write(body)

    # -------------------------------------------------------------- checks
    def _host_is_allowed(self) -> bool:
        return self.headers.get("Host", "") in self.state.allowed_hosts()

    def _token_is_valid(self, query: dict) -> bool:
        supplied = self.headers.get("X-CutContent-Token") or (query.get("token") or [""])[0]
        return secrets.compare_digest(supplied, self.state.token)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > 1_000_000:
            raise ValueError("request body too large")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    # ------------------------------------------------------------- routing
    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        if not self._host_is_allowed():
            self._send_error_json(HTTPStatus.FORBIDDEN, "Unexpected Host header; open the address printed by 'cutcontent gui'.")
            return
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)
        self.engine_response = path.startswith("/play/")
        try:
            if method == "GET" and path in ("/", "/index.html"):
                self._serve_index()
            elif method == "GET" and path.startswith("/static/"):
                self._serve_static(path[len("/static/") :])
            elif method == "GET" and path.startswith("/play/"):
                self._serve_game_session(path[len("/play/") :])
            elif path.startswith("/api/"):
                if not self._token_is_valid(query):
                    self._send_error_json(HTTPStatus.UNAUTHORIZED, "Missing or wrong session token. Reload the page.")
                    return
                self._serve_api(method, path[len("/api/") :].strip("/").split("/"), query)
            else:
                self._send_error_json(HTTPStatus.NOT_FOUND, "Not found")
        except FolderPermissionError as error:
            self._send_error_json(HTTPStatus.FORBIDDEN, str(error))
        except PreviewError as error:
            self._send_error_json(HTTPStatus.UNPROCESSABLE_ENTITY, str(error))
        except (ValueError, KeyError, FileNotFoundError) as error:
            self._send_error_json(HTTPStatus.BAD_REQUEST, str(error))
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as error:
            traceback.print_exc()
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(error).__name__}: {error}")

    def _serve_index(self) -> None:
        html = (STATIC_DIRECTORY / "index.html").read_text(encoding="utf-8")
        html = html.replace("__SESSION_TOKEN__", self.state.token)
        self._send(200, "text/html; charset=utf-8", html.encode("utf-8"))

    def _serve_static(self, relative: str) -> None:
        target = (STATIC_DIRECTORY / relative).resolve()
        if STATIC_DIRECTORY not in target.parents or not target.is_file():
            self._send_error_json(HTTPStatus.NOT_FOUND, "Not found")
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        self._send(200, content_type, target.read_bytes())

    def _serve_api(self, method: str, parts: list[str], query: dict) -> None:
        state = self.state
        route = parts[0] if parts else ""
        if method == "GET" and route == "overview":
            payload = service.overview()
            library_file = data_directory() / "library.json"
            builds = json.loads(library_file.read_text(encoding="utf-8")) if library_file.is_file() else service.discover_builds()
            payload["games"] = service.group_builds_by_title(self._attach_reports(builds))
            payload["game_launch_note"] = "A free camera through level geometry is not a game start."
            self._send_json(payload)
        elif method == "POST" and route == "library":
            builds = service.discover_builds()
            self._send_json({"games": service.group_builds_by_title(self._attach_reports(builds))})
        elif method == "POST" and route == "scan":
            body = self._read_json_body()
            self._send_json({"job_id": state.start_scan(str(body.get("path", "")))})
        elif method == "GET" and route == "jobs" and len(parts) == 2:
            job = state.jobs.get(parts[1])
            if job is None:
                self._send_error_json(HTTPStatus.NOT_FOUND, "Unknown job")
            else:
                self._send_json(job)
        elif method == "GET" and route == "report" and len(parts) == 2:
            report = load_report(parts[1])
            if report is None:
                self._send_error_json(HTTPStatus.NOT_FOUND, "This build has not been scanned yet.")
                return
            service.folder_rules.require_inside_allowed_folder(report["path"])
            if report["adapter"] == "quake":
                from cutcontent.platforms.quake_engine import cached_game_data, game_launch_status, resolve_game_directory
                report["game_launch"] = game_launch_status(cached_game_data(resolve_game_directory(Path(report["path"]))))
                if self.state.allow_unverified_engine:
                    from cutcontent.platforms.browser_engines import quake_browser_engine_status
                    report["game_launch"] = quake_browser_engine_status(require_verification=False)
            elif report["adapter"] == "cartridge_file_table":
                report["native_gameplay"] = native_build_status(parts[1])
            self._send_json(report)
        elif method == "GET" and route == "directory" and len(parts) == 2:
            from cutcontent import directory
            report = load_report(parts[1])
            if report is None:
                self._send_error_json(HTTPStatus.NOT_FOUND, "This build has not been scanned yet.")
                return
            service.folder_rules.require_inside_allowed_folder(report["path"])
            # Only files up to 256 MiB are hashed here so the page stays responsive;
            # `cutcontent directory match` hashes larger images too.
            build = directory.build_from_report(report, maximum_file_bytes=256 * 1024 * 1024)
            self._send_json({"matches": directory.match_build(directory.load_entries(), build),
                             "files_hashed": len(build["sha256"])})
        elif method == "POST" and route == "native-launch" and len(parts) == 2:
            body = self._read_json_body()
            recipe = body.get("recipe", "")
            if not isinstance(recipe, str):
                raise ValueError("The input sequence must use a registered name.")
            session_id, payload = state.native_games.start(parts[1], recipe)
            self._send_json({"session_id": session_id, **payload})
        elif route == "native-session" and len(parts) == 3:
            session_id, action = parts[1:]
            if method == "POST" and action == "stop":
                state.native_games.stop(session_id)
                self._send_json({"stopped": True})
            elif method == "POST" and action == "input":
                self._send_json(state.native_games.get(session_id).operate(self._read_json_body()))
            elif method == "GET" and action == "frame.png":
                session = state.native_games.get(session_id)
                self._send(200, "image/png", session.latest_frame)
            elif method == "GET" and action == "audio.wav":
                self._send_body_with_ranges("audio/wav", state.native_games.get(session_id).audio())
            else:
                self._send_error_json(HTTPStatus.NOT_FOUND, "Unknown runtime action.")
        elif method == "POST" and route == "game-launch" and len(parts) == 3:
            launch = prepare_game_launch(parts[1], parts[2], state.allow_unverified_engine)
            # Retain a bounded number of sessions; each holds paths, never game bytes.
            while len(state.game_sessions) >= 8:
                del state.game_sessions[next(iter(state.game_sessions))]
            session_id = secrets.token_urlsafe(24)
            state.game_sessions[session_id] = launch
            self._send_json({"url": f"/play/{session_id}/index.html", "map": launch.level_name})
        elif method == "GET" and route == "preview" and len(parts) == 3:
            self._serve_preview(parts[1], parts[2], query)
        elif method == "GET" and route == "task" and len(parts) == 2:
            client = (query.get("client") or ["claude"])[0]
            items = [item for item in (query.get("items") or [""])[0].split(",") if item]
            question = (query.get("question") or [""])[0]
            self._send_json({"text": service.investigation_task(parts[1], client, items, question)})
        elif method == "GET" and route == "doctor":
            self._send_json({"checks": service.doctor_checks()})
        elif method == "GET" and route == "formats":
            self._send_json({"formats": service.format_support_rows()})
        else:
            self._send_error_json(HTTPStatus.NOT_FOUND, "Unknown API call")

    @staticmethod
    def _attach_reports(builds: list[dict]) -> list[dict]:
        from cutcontent.core.scan_report import list_reports

        reports = {summary["build_id"]: summary for summary in list_reports()}
        for build in builds:
            summary = reports.get(build["build_id"])
            build["report"] = summary
            if summary:
                for field in ("adapter", "platform", "format_name"):
                    build[field] = summary[field]
        return builds

    def _serve_game_session(self, relative: str) -> None:
        session_id, separator, resource = relative.partition("/")
        launch = self.state.game_sessions.get(session_id)
        if not separator or launch is None:
            self._send_error_json(HTTPStatus.NOT_FOUND, "Unknown game session.")
            return
        launch.require_current_access()
        static_files = {"index.html": ("game-player.html", "text/html; charset=utf-8"), "player.js": ("game-player.js", "text/javascript; charset=utf-8"), "player.css": ("game-player.css", "text/css; charset=utf-8")}
        if resource in static_files:
            name, content_type = static_files[resource]
            self._send(200, content_type, (STATIC_DIRECTORY / name).read_bytes())
        elif resource == "manifest.json":
            self._send_json(launch.manifest())
        elif resource in ("engine.js", "engine.wasm"):
            content_type = "application/wasm" if resource.endswith(".wasm") else "text/javascript; charset=utf-8"
            self._send(200, content_type, launch.read_engine_file(resource))
        elif resource.startswith("files/") and resource[6:].isdigit():
            self._stream_game_file(launch.game_file_path(int(resource[6:])))
        else:
            self._send_error_json(HTTPStatus.NOT_FOUND, "Unknown game resource.")

    def _stream_game_file(self, path: Path) -> None:
        """Stream PAKs without keeping a whole game archive in server memory."""
        with path.open("rb") as handle:
            size = path.stat().st_size
            start, end = 0, size - 1
            range_header = self.headers.get("Range")
            if range_header:
                try:
                    unit, bounds = range_header.split("=", 1)
                    first, last = bounds.split("-", 1)
                    if unit != "bytes" or "," in bounds:
                        raise ValueError("unsupported range")
                    start = int(first) if first else max(0, size - int(last))
                    end = min(int(last), size - 1) if first and last else size - 1
                    if not 0 <= start <= end < size:
                        raise ValueError("range outside file")
                except ValueError:
                    self._send_error_json(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, "This byte range is outside the game file.")
                    return
            self.send_response(206 if range_header else 200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(max(0, end - start + 1)))
            self.send_header("Accept-Ranges", "bytes")
            if range_header:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self._common_headers()
            self.end_headers()
            if self.command == "HEAD":
                return
            handle.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = handle.read(min(remaining, 1024 * 1024))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _serve_preview(self, build_id: str, item_id: str, query: dict) -> None:
        options: dict = {"thumbnail": (query.get("thumbnail") or [""])[0] == "1"}
        for name in ("offset", "bits", "columns"):
            value = (query.get(name) or [""])[0]
            if value:
                options[name] = int(value, 0)  # accepts decimal and 0x... hexadecimal
        key = f"{build_id}/{item_id}/" + "/".join(f"{name}={options[name]}" for name in sorted(options))
        cached = self.state.preview_cache.get(key)
        if cached is None:
            result = service.preview_item(build_id, item_id, options)
            cached = (result.content_type, result.body)
            self.state.preview_cache.put(key, cached)
        content_type, body = cached
        self._send_body_with_ranges(content_type, body)


def make_server(port: int) -> tuple[ThreadingHTTPServer, ApplicationState]:
    last_error = None
    for candidate in range(port, port + 20):
        state = ApplicationState(candidate)
        handler = type("BoundRequestHandler", (RequestHandler,), {"state": state})
        class ApplicationServer(ThreadingHTTPServer):
            def server_close(self) -> None:
                state.native_games.close()
                super().server_close()
        try:
            server = ApplicationServer((LISTEN_ADDRESS, candidate), handler)
        except OSError as error:
            last_error = error
            continue
        server.daemon_threads = True
        return server, state
    raise OSError(f"No free port between {port} and {port + 19}: {last_error}")
