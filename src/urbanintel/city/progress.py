from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import deque
from pathlib import Path

STAGES: list[tuple[str, str]] = [
    ("resolve", "Resolving the city boundary"),
    ("search", "Looking for datasets"),
    ("download", "Downloading datasets"),
    ("process", "Processing datasets"),
    ("train", "Training the image model"),
    ("evaluate", "Evaluating on the held-out period"),
    ("forecast", "Forecasting urban growth"),
    ("economy", "Analysing economic activity"),
    ("news_fetch", "Fetching news information"),
    ("news_process", "Processing news information"),
    ("opportunity", "Scoring expansion opportunities"),
    ("charts", "Displaying charts"),
]


class Status:
    def __init__(self, path: Path, *, city: str, run_id: str, stages=STAGES):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.tail: deque[str] = deque(maxlen=12)
        self.last_write = 0.0
        self.data = {
            "city": city, "run_id": run_id, "state": "running", "pid": os.getpid(),
            "started": time.time(), "updated": time.time(), "finished": None,
            "stages": [{"key": k, "label": lbl, "state": "pending", "done": 0, "total": None,
                        "module": None, "detail": None, "started": None, "ended": None,
                        "note": None} for k, lbl in stages],
            "current": None, "bytes_downloaded": 0, "estimated_bytes": None,
            "error": None, "log_tail": [],
        }
        self.write(force=True)

    def _stage(self, key: str) -> dict:
        for s in self.data["stages"]:
            if s["key"] == key:
                return s
        raise KeyError(key)

    def begin(self, key: str, *, total: int | None = None, module: str | None = None,
              detail: str | None = None) -> None:
        with self.lock:
            s = self._stage(key)
            s.update(state="running", total=total, done=0, module=module, detail=detail,
                     started=time.time())
            self.data["current"] = key
            self.write(force=True)

    def update(self, key: str, *, done: int | None = None, total: int | None = None,
               module: str | None = None, detail: str | None = None, advance: int = 0) -> None:
        with self.lock:
            s = self._stage(key)
            if total is not None:
                s["total"] = total
            if done is not None:
                s["done"] = done
            s["done"] += advance
            if module is not None:
                s["module"] = module
            if detail is not None:
                s["detail"] = detail
            self.write()

    def end(self, key: str, *, state: str = "done", note: str | None = None) -> None:
        with self.lock:
            s = self._stage(key)
            s.update(state=state, ended=time.time())
            if note:
                s["note"] = note
            if state == "done" and s["total"]:
                s["done"] = s["total"]
            self.write(force=True)

    def skip(self, key: str, note: str) -> None:
        with self.lock:
            self._stage(key).update(state="skipped", note=note, ended=time.time())
            self.write(force=True)

    def add_bytes(self, n: int) -> None:
        with self.lock:
            self.data["bytes_downloaded"] += int(n)
            self.write()

    def set(self, **kw) -> None:
        with self.lock:
            self.data.update(kw)
            self.write(force=True)

    def log(self, msg: str) -> None:
        with self.lock:
            self.tail.append(time.strftime("%H:%M:%S ") + msg)
            self.write()

    def finish(self, state: str = "done", error: str | None = None) -> None:
        with self.lock:
            self.data.update(state=state, finished=time.time(), error=error, current=None)
            for s in self.data["stages"]:
                if s["state"] == "running":
                    s.update(state="failed" if state == "failed" else "done", ended=time.time())
            self.write(force=True)

    def write(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self.last_write < 0.4:
            return
        self.last_write = now
        self.data["updated"] = now
        self.data["log_tail"] = list(self.tail)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
        # A reader holding the file open on Windows blocks the rename for a moment, so retry
        for _ in range(20):
            try:
                os.replace(tmp, self.path)
                return
            except PermissionError:
                time.sleep(0.05)


class StatusLogHandler(logging.Handler):
    def __init__(self, status: Status):
        super().__init__(level=logging.INFO)
        self.status = status

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.status.log(record.getMessage()[:200])
        except Exception:  # noqa: BLE001
            pass


def read_status(path: Path) -> dict | None:
    for _ in range(5):
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, PermissionError):
            time.sleep(0.05)
    return None
