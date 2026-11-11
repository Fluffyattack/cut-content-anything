"""Run a separately installed interpreter against a read-only local cartridge.

Only documented controller operations cross the HTTP boundary. Screenshots are
the core's actual framebuffers and sound is its actual PCM output. Private runs
and save data stay outside both the source checkout and the original game folder.
"""
from __future__ import annotations

import atexit
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import queue
import secrets
import signal
import subprocess
import sys
import threading
import time
import wave

from cutcontent.core.developer_menus import BUTTON_BITS, developer_menu_commands, developer_menu_recipes
from cutcontent.core.folders import require_inside_allowed_folder
from cutcontent.core.png_writer import encode_png
from cutcontent.core.scan_report import load_report
from cutcontent.core.settings import data_directory, write_json_atomically
from cutcontent.platforms.base import PreviewError

SESSION_IDLE_SECONDS = 15 * 60
MAXIMUM_SESSION_SECONDS = 60 * 60
COMMAND_TIMEOUT_SECONDS = 90
MAXIMUM_AUDIO_BYTES = 48000 * 4 * 10


def native_player_directory() -> Path:
    configured = os.environ.get("CUT_CONTENT_CARTRIDGE_INTERPRETER_DIR")
    return Path(configured).expanduser() if configured else data_directory() / "engines" / "cartridge-interpreter"


def native_player_status() -> dict:
    directory = native_player_directory()
    executable = directory / "cartridge_player"
    try:
        build = json.loads((directory / "build.json").read_text(encoding="utf-8"))
        if build.get("protocol_version") != 1:
            raise ValueError("The installed control protocol is not supported.")
        if not executable.is_file() or executable.is_symlink() or not os.access(executable, os.X_OK):
            raise ValueError("The local player is missing or is not executable.")
        if hashlib.sha256(executable.read_bytes()).hexdigest() != build.get("player_sha256"):
            raise ValueError("The local player does not match its build manifest.")
        return {"available": True, "engine": build.get("engine", "local interpreter"), "revision": build.get("revision", ""),
                "reason": "Local interpreter with actual game screens, audio, buttons and touch input. Speed depends on your computer.",
                "save_persistence_supported": bool(build.get("save_persistence_supported"))}
    except (OSError, ValueError, KeyError) as error:
        return {"available": False, "reason": f"Install a compatible local interpreter outside this checkout; see docs/LOCAL_INTERPRETER.md. {error}"}


def cartridge_for_build(build_id: str) -> Path:
    report = load_report(build_id)
    if report is None or report.get("adapter") != "cartridge_file_table":
        raise PreviewError("No local runtime player is configured for this build.")
    path = require_inside_allowed_folder(report["path"])
    if not path.is_file():
        raise PreviewError("The scanned game file no longer exists.")
    return path


def native_build_status(build_id: str) -> dict:
    path = cartridge_for_build(build_id)
    return {**native_player_status(), "recipes": developer_menu_recipes(path)}


class NativeGameSession:
    def __init__(self, build_id: str, path: Path, recipe_id: str = ""):
        self.build_id = build_id
        self.path = path
        self.created_at = self.last_used = time.monotonic()
        self.lock = threading.RLock()
        self.closed = False
        self.capture_number = 0
        self.latest_frame = b""
        self.latest_state: dict = {}
        self.transcript: list[dict] = []
        cartridge_digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                cartridge_digest.update(chunk)
        self.cartridge_sha256 = cartridge_digest.hexdigest()
        save_directory = data_directory() / "private-saves" / "cartridge-interpreter"
        save_directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        save_directory.chmod(0o700)
        self.save_file = save_directory / (self.cartridge_sha256 + ".sav")
        self.directory = data_directory() / "runtime" / ("gallery-" + secrets.token_hex(12))
        self.directory.parent.mkdir(parents=True, exist_ok=True)
        self.messages: queue.Queue = queue.Queue()
        self.error_log = self.directory.with_suffix(".stderr.log").open("xb")
        self.directory.with_suffix(".stderr.log").chmod(0o600)
        # A fresh interpreter process owns all writes. Never pass a shell command
        # or a browser-supplied path to it. The worker installs resource limits.
        self.process = subprocess.Popen(
            [sys.executable, "-m", "cutcontent.core.native_gameplay", "--launch-worker",
             str(native_player_directory() / "cartridge_player"), str(path), str(self.directory), str(self.save_file)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.error_log,
            text=True, bufsize=1, start_new_session=True,
        )
        self.reader = threading.Thread(target=self._read_responses, name="cartridge-responses", daemon=True)
        self.reader.start()
        try:
            self.latest_state = self._response()
            if not self.latest_state.get("ok"):
                raise PreviewError("The local interpreter could not start the game.")
            commands = developer_menu_commands(recipe_id) if recipe_id else ["step 180"]
            for command in commands:
                self.command(command)
            self.capture()
        except BaseException:
            self.close()
            raise

    def _read_responses(self) -> None:
        try:
            for line in self.process.stdout:
                if len(line) > 1024 * 1024:
                    self.messages.put({"ok": False, "error": "The local player's response exceeds the supported length."})
                    break
                try:
                    payload = json.loads(line)
                except ValueError:
                    continue  # optional core diagnostic messages are not protocol replies
                if isinstance(payload, dict) and "ok" in payload:
                    self.messages.put(payload)
        finally:
            self.messages.put(None)

    def _response(self) -> dict:
        try:
            reply = self.messages.get(timeout=COMMAND_TIMEOUT_SECONDS)
        except queue.Empty:
            raise PreviewError("The local player did not respond in time. This run will be stopped.") from None
        if reply is None:
            raise PreviewError("The local player ended this run; see the private run report for diagnostics.")
        if not reply.get("ok"):
            raise PreviewError(str(reply.get("error", "The local player rejected this input.")))
        return reply

    def require_access(self) -> None:
        now = time.monotonic()
        if self.closed or now - self.last_used > SESSION_IDLE_SECONDS or now - self.created_at > MAXIMUM_SESSION_SECONDS:
            self.close()
            raise PreviewError("This game run has ended. Start the game again.")
        require_inside_allowed_folder(self.path)
        self.last_used = now

    def command(self, text: str) -> dict:
        with self.lock:
            self.require_access()
            self.process.stdin.write(text + "\n")
            self.process.stdin.flush()
            reply = self._response()
            self.transcript.append({"command": text, "response": reply})
            if "frames_executed" in reply:
                self.latest_state.update(reply)
            return reply

    def capture(self) -> dict:
        with self.lock:
            name = f"frame-{self.capture_number:06d}"
            self.capture_number += 1
            self.command("capture " + name)
            # Ignore all returned paths. Read only this session's fixed capture.
            rgba = (self.directory / (name + ".rgba")).read_bytes()
            if len(rgba) != 256 * 384 * 4:
                raise PreviewError("The screen capture has an invalid size.")
            self.latest_frame = encode_png(256, 384, rgba, channels=4)
            (self.directory / (name + ".png")).write_bytes(self.latest_frame)
            # PNG is a lossless copy of the real pixels. Retaining duplicate raw
            # files for each button press would unnecessarily fill small disks.
            for suffix in (".rgba", ".ppm"):
                (self.directory / (name + suffix)).unlink(missing_ok=True)
            if self.capture_number > 512:
                oldest = f"frame-{self.capture_number - 513:06d}"
                for suffix in (".png", ".json"):
                    (self.directory / (oldest + suffix)).unlink(missing_ok=True)
            return self.public_state()

    def public_state(self) -> dict:
        return {"build_id": self.build_id, "capture": self.capture_number, "state": copy.deepcopy(self.latest_state),
                "width": 256, "height": 384}

    @staticmethod
    def _integer(value, low: int, high: int, name: str) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
            raise ValueError(f"{name} must be an integer from {low} to {high}.")
        return value

    def operate(self, operation: dict) -> dict:
        with self.lock:
            self.require_access()
            action = operation.get("action")
            frames = self._integer(operation.get("frames", 6), 1, 300, "Frames")
            try:
                if action == "step":
                    self.command(f"step {frames}")
                elif action == "button":
                    button = operation.get("button")
                    if not isinstance(button, str) or button not in BUTTON_BITS:
                        raise ValueError("Unknown game button.")
                    self.command(f"keys {4095 ^ (1 << BUTTON_BITS[button])}")
                    self.command(f"step {frames}")
                    self.command("keys 4095")
                    self.command("step 6")
                elif action == "touch":
                    points = operation.get("points")
                    if not isinstance(points, list) or not 1 <= len(points) <= 128:
                        raise ValueError("Touch input needs between 1 and 128 screen points.")
                    validated_points = []
                    for point in points:
                        if not isinstance(point, list) or len(point) != 2:
                            raise ValueError("Each touch point needs X and Y coordinates.")
                        validated_points.append((self._integer(point[0], 0, 255, "X"), self._integer(point[1], 0, 191, "Y")))
                    draw_button = operation.get("button", "")
                    if not isinstance(draw_button, str) or (draw_button and draw_button not in BUTTON_BITS):
                        raise ValueError("Unknown held game button.")
                    if draw_button:
                        self.command(f"keys {4095 ^ (1 << BUTTON_BITS[draw_button])}")
                    for x, y in validated_points:
                        self.command(f"touch {x} {y}")
                        self.command("step 2")
                    self.command("release_touch")
                    self.command("keys 4095")
                    self.command(f"step {frames}")
                elif action == "microphone":
                    if not self.latest_state.get("microphone_supported"):
                        raise ValueError("The installed player does not support emulated blowing.")
                    self.command("microphone 1")
                    self.command(f"step {frames}")
                    self.command("microphone 0")
                    self.command("step 6")
                else:
                    raise ValueError("Unknown game input.")
                return self.capture()
            except (BrokenPipeError, PreviewError):
                self.close()
                raise

    def audio(self) -> bytes:
        """Return the most recent real stereo PCM as a bounded, valid WAV."""
        with self.lock:
            self.require_access()
            path = self.directory / "audio.s16le"
            if not path.is_file():
                raise PreviewError("The player has not recorded any audio yet.")
            size = path.stat().st_size // 4 * 4
            # GET must be repeatable: browser retries, decoding and seeking all
            # receive the same most recent real clip until more frames execute.
            start = max(0, size - MAXIMUM_AUDIO_BYTES)
            with path.open("rb") as handle:
                handle.seek(start)
                samples = handle.read(size - start)
            output = io.BytesIO()
            with wave.open(output, "wb") as audio:
                audio.setnchannels(2)
                audio.setsampwidth(2)
                audio.setframerate(48000)
                audio.writeframes(samples)
            return output.getvalue()

    def close(self) -> None:
        with self.lock:
            if self.closed:
                return
            self.closed = True
            if self.process.poll() is None:
                try:
                    self.process.stdin.write("quit\n")
                    self.process.stdin.flush()
                    self.process.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    os.killpg(self.process.pid, signal.SIGTERM)
                    try:
                        self.process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(self.process.pid, signal.SIGKILL)
                        self.process.wait()
            self.error_log.close()
            if self.directory.exists():
                write_json_atomically(self.directory / "observations.json", {
                    "build_id": self.build_id, "hardware_test": False,
                    "cartridge_sha256": self.cartridge_sha256,
                    "state": self.latest_state, "operations": self.transcript,
                    "process_exit_code": self.process.returncode,
                })


class NativeGameManager:
    """One running interpreter keeps small computers responsive."""
    def __init__(self):
        self.lock = threading.RLock()
        self.sessions: dict[str, NativeGameSession] = {}
        self.closed = threading.Event()
        threading.Thread(target=self._expire_sessions, daemon=True, name="cartridge-expiry").start()
        atexit.register(self.close)

    def start(self, build_id: str, recipe_id: str = "") -> tuple[str, dict]:
        with self.lock:
            status = native_player_status()
            if not status["available"]:
                raise PreviewError(status["reason"])
            path = cartridge_for_build(build_id)
            recipes = developer_menu_recipes(path)
            if recipe_id and recipe_id not in {recipe["id"] for recipe in recipes}:
                raise PreviewError("This input sequence is not verified for the exact game build.")
            for session in self.sessions.values():
                session.close()
            self.sessions.clear()
            session = NativeGameSession(build_id, path, recipe_id)
            session_id = secrets.token_urlsafe(24)
            self.sessions[session_id] = session
            return session_id, session.public_state()

    def get(self, session_id: str) -> NativeGameSession:
        with self.lock:
            session = self.sessions.get(session_id)
            if session is None:
                raise PreviewError("Unknown game run.")
            session.require_access()
            return session

    def stop(self, session_id: str) -> None:
        with self.lock:
            session = self.sessions.pop(session_id, None)
            if session is not None:
                session.close()

    def _expire_sessions(self) -> None:
        while not self.closed.wait(30):
            with self.lock:
                now = time.monotonic()
                for session_id, session in list(self.sessions.items()):
                    if now - session.last_used > SESSION_IDLE_SECONDS or now - session.created_at > MAXIMUM_SESSION_SECONDS:
                        session.close()
                        self.sessions.pop(session_id, None)

    def close(self) -> None:
        self.closed.set()
        with self.lock:
            for session in self.sessions.values():
                session.close()
            self.sessions.clear()


def _launch_worker() -> None:
    import resource
    executable, cartridge, output, save_file = sys.argv[2:]
    resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024**2, 1536 * 1024**2))
    resource.setrlimit(resource.RLIMIT_FSIZE, (768 * 1024**2, 768 * 1024**2))
    resource.setrlimit(resource.RLIMIT_CPU, (1800, 1800))
    os.execv(executable, [executable, cartridge, output, "--save-file", save_file])


if __name__ == "__main__" and len(sys.argv) == 6 and sys.argv[1] == "--launch-worker":
    _launch_worker()
