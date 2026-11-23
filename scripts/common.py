"""Пути, CSV, паузы, robots.txt, сырой слой."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import time
import urllib.error
import urllib.request

import pandas as pd
import requests
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
CLEAN = DATA / "clean"
DERIVED = DATA / "derived"
REFERENCE = DATA / "reference"
LOGS = ROOT / "logs"
DOCS = ROOT / "docs"
DIGEST = ROOT / "digest"
MSK = ZoneInfo("Europe/Moscow")
UA = "AlmanacCollector/0.1 (research; almanac volume 2; respects robots.txt)"


def now_msk() -> datetime:
    return datetime.now(MSK)


def iso_now() -> str:
    return now_msk().isoformat(timespec="seconds")


def ensure_tree() -> None:
    folders = [
        RAW / "moex_iss" / "shares",
        RAW / "moex_iss" / "indices",
        RAW / "moex_iss" / "bonds",
        RAW / "moex_iss" / "dividends",
        RAW / "cbr",
        RAW / "fred",
        RAW / "solar",
        RAW / "weather",
        RAW / "fundamentals",
        RAW / "news",
        CLEAN,
        DERIVED,
        REFERENCE / "legacy_vol1",
        LOGS,
        DIGEST / "weekly",
        DIGEST / "monthly",
        DOCS,
    ]
    for folder in folders:
        folder.mkdir(parents=True, exist_ok=True)
        marker = folder / ".gitkeep"
        if not any(path.name != ".gitkeep" for path in folder.iterdir()) and not marker.exists():
            marker.write_text("", encoding="utf-8")


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    material = [{key: _cell(row.get(key)) for key in columns} for row in rows]
    frame = pd.DataFrame(material, columns=columns)
    frame.to_csv(path, index=False)


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return ""
        text = f"{value:.8f}".rstrip("0").rstrip(".")
        return text if text not in ("-0", "") else "0"
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def append_unique(path: Path, columns: list[str], rows: list[dict], key_fields: list[str]) -> int:
    existing = read_csv(path)
    seen = {tuple(row.get(field, "") for field in key_fields) for row in existing}
    added = []
    for row in rows:
        key = tuple(str(row.get(field, "") or "") for field in key_fields)
        if key in seen:
            continue
        seen.add(key)
        added.append(row)
    write_csv(path, columns, existing + added)
    return len(added)


class HttpClient:
    def __init__(self, pause_seconds: float = 1.0):
        self.pause_seconds = pause_seconds
        self._last = 0.0
        self._robots: dict[str, tuple[RobotFileParser | None, float]] = {}

    def check_robots(self, url: str) -> tuple[bool, str]:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        parser, delay = self._robots.get(base, (None, 0.0))
        if parser is None and base not in self._robots:
            parser, delay, reason = self._load_robots(base)
            if parser is False:
                return False, reason
            self._robots[base] = (parser, delay)
        parser, delay = self._robots[base]
        wait = max(self.pause_seconds, delay or 0.0)
        if parser is None:
            return True, "robots.txt нет, ограничение не задано"
        allowed = parser.can_fetch(UA, url)
        if not allowed:
            return False, "robots.txt запрещает URL"
        self.pause_seconds = max(self.pause_seconds, wait)
        return True, "разрешено"

    def _load_robots(self, base: str):
        robots_url = base + "/robots.txt"
        request = urllib.request.Request(robots_url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None, 0.0, "404"
            return False, 0.0, f"robots.txt HTTP {error.code}"
        except Exception as error:  # noqa: BLE001 — сбой robots останавливает только этот хост
            return False, 0.0, f"robots.txt недоступен: {error}"
        parser = RobotFileParser()
        parser.parse(body.splitlines())
        delay = 0.0
        for line in body.splitlines():
            if line.lower().startswith("crawl-delay:"):
                try:
                    delay = float(line.split(":", 1)[1].strip())
                except ValueError:
                    delay = 0.0
        return parser, delay, "ok"

    def get(self, url: str) -> bytes:
        allowed, reason = self.check_robots(url)
        if not allowed:
            raise PermissionError(reason)
        last_error = None
        for attempt in range(3):
            self._pause()
            try:
                response = requests.get(url, headers={"User-Agent": UA}, timeout=60)
                response.raise_for_status()
                return response.content
            except Exception as error:  # noqa: BLE001 — повтор по правилу 0.6
                last_error = error
                time.sleep(2**attempt)
        raise RuntimeError(f"не удалось скачать {url}: {last_error}")

    def _pause(self) -> None:
        elapsed = time.monotonic() - self._last
        if self._last and elapsed < self.pause_seconds:
            time.sleep(self.pause_seconds - elapsed)
        self._last = time.monotonic()


def save_raw(path: Path, payload: bytes, url: str) -> bool:
    """Вернуть True, только если файл создан. Существующий raw не трогаем."""
    fetches = LOGS / "fetches.csv"
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    append_unique(
        fetches,
        ["path", "url", "fetched_at"],
        [{"path": str(path.relative_to(ROOT)), "url": url, "fetched_at": iso_now()}],
        ["path"],
    )
    return True


def fetched_at_for(path: Path) -> str:
    for row in read_csv(LOGS / "fetches.csv"):
        if row.get("path") == str(path.relative_to(ROOT)):
            return row.get("fetched_at", "")
    return ""


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_thresholds() -> dict:
    path = REFERENCE / "plan_thresholds.json"
    return json.loads(path.read_text(encoding="utf-8"))
