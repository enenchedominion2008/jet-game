"""Serve Sky Patrol, with a tiny JSON progress API.

Run from the project root with: python3 progress_server.py
Then open http://127.0.0.1:8000/static/game.html
"""

from __future__ import annotations

import argparse
import json
import re
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / ".game-data"
DATA_FILE = DATA_DIR / "progress.json"
PLAYER_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
LOCK = threading.Lock()


def read_progress() -> dict[str, dict[str, int]]:
    try:
        payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def write_progress(progress: dict[str, dict[str, int]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = DATA_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(progress, indent=2), encoding="utf-8")
    temporary.replace(DATA_FILE)


class GameHandler(SimpleHTTPRequestHandler):
    """Static file server plus /api/progress/<pilot-id> endpoints."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def api_player_id(self) -> str | None:
        path = urlsplit(self.path).path
        match = re.fullmatch(r"/api/progress/([^/]+)", path)
        if not match or not PLAYER_ID.fullmatch(match.group(1)):
            return None
        return match.group(1)

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path.startswith("/.game-data"):
            self.send_error(404)
            return
        if path.startswith("/api/progress/"):
            player_id = self.api_player_id()
            if player_id is None:
                self.send_json(400, {"error": "Invalid pilot ID"})
                return
            with LOCK:
                record = read_progress().get(player_id)
            if record is None:
                self.send_json(404, {"error": "No saved progress for this pilot"})
                return
            self.send_json(200, record)
            return
        super().do_GET()

    def do_POST(self) -> None:
        player_id = self.api_player_id()
        if player_id is None:
            self.send_json(404, {"error": "Unknown progress endpoint"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 4096:
                raise ValueError("Invalid request size")
            payload = json.loads(self.rfile.read(length))
            stage = int(payload["stage"])
            unlocked = int(payload["unlocked"])
            if not 1 <= stage <= 12 or not 1 <= unlocked <= 12:
                raise ValueError("Stage must be between 1 and 12")
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            self.send_json(400, {"error": "Expected stage and unlocked values from 1 to 12"})
            return

        record = {"stage": stage, "unlocked": max(stage, unlocked)}
        with LOCK:
            progress = read_progress()
            progress[player_id] = record
            write_progress(progress)
        self.send_json(200, record)

    def log_message(self, format: str, *args) -> None:
        # Keep normal static requests quiet while retaining API errors.
        if args and str(args[1:2]).find("404") >= 0:
            super().log_message(format, *args)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve Sky Patrol and save campaign progress.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), GameHandler)
    print(f"Sky Patrol is ready at http://{args.host}:{args.port}/static/game.html")
    print("Progress data is stored in .game-data/progress.json")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Sky Patrol server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
