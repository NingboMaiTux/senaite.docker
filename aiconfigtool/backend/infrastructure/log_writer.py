"""JSONL 日志写入器（stdlib json，追加写入，线程安全，自动清理）。

严格按技术设计文档 13.2/13.3：
- server_{date}.log   HTTP 请求 + 应用事件
- pipeline_{date}.log 流水线步骤级日志
格式：每行一个 JSON 对象，含 ts/level/step/run_id/msg/elapsed_ms。
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta


def _default_log_dir() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "..", "data", "logs")


_instance: "LogWriter | None" = None


def get_log_writer() -> "LogWriter":
    global _instance
    if _instance is None:
        _instance = LogWriter()
    return _instance


class LogWriter:
    """线程安全的 JSONL 日志写入器。"""

    def __init__(self, log_dir: str | None = None, max_days: int = 30):
        self._dir = os.path.abspath(log_dir or _default_log_dir())
        os.makedirs(self._dir, exist_ok=True)
        self._max_days = max_days
        self._lock = threading.Lock()

    def _path(self, category: str) -> str:
        today = datetime.now().strftime("%Y%m%d")
        return os.path.join(self._dir, f"{category}_{today}.log")

    def write(self, category: str, level: str, message: str, **extra) -> None:
        entry = {
            "ts": datetime.now().isoformat(),
            "level": level,
            "msg": message,
            **extra,
        }
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with self._lock:
            with open(self._path(category), "a", encoding="utf-8", newline="\n") as f:
                f.write(line)

    def info(self, category: str, message: str, **extra) -> None:
        self.write(category, "INFO", message, **extra)

    def warn(self, category: str, message: str, **extra) -> None:
        self.write(category, "WARN", message, **extra)

    def error(self, category: str, message: str, **extra) -> None:
        self.write(category, "ERROR", message, **extra)

    def cleanup(self) -> int:
        """删除超过 max_days 的日志文件。返回删除数量。"""
        cutoff = datetime.now() - timedelta(days=self._max_days)
        deleted = 0
        try:
            for name in os.listdir(self._dir):
                if not name.endswith(".log"):
                    continue
                path = os.path.join(self._dir, name)
                try:
                    mtime = datetime.fromtimestamp(os.path.getmtime(path))
                    if mtime < cutoff:
                        os.remove(path)
                        deleted += 1
                except OSError:
                    pass
        except FileNotFoundError:
            pass
        return deleted
