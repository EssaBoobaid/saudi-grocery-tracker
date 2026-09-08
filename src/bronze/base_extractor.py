import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from config.settings import REQUEST_TIMEOUT_SECONDS, USER_AGENT


class BaseExtractor:
    """Shared HTTP and raw JSON persistence for store extractors."""

    def __init__(self, store_name: str, base_url: str, output_dir: Path) -> None:
        self.store_name = store_name
        self.base_url = base_url
        self.output_dir = output_dir
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

    def fetch(self, url: str | None = None) -> Any:
        response = self.session.get(url or self.base_url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()

    def save_raw(self, payload: Any, suffix: str = "products") -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = self.output_dir / f"{suffix}_{timestamp}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
