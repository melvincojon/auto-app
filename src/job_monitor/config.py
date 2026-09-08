from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .errors import SourceError


@dataclass(frozen=True, slots=True)
class CompanyConfig:
    company: str
    adapter: str
    values: dict[str, Any]

    def get(self, name: str, default: Any = None) -> Any:
        return self.values.get(name, default)

    def require(self, name: str) -> Any:
        if name not in self.values:
            raise SourceError("configuration_drift", f"missing required config key: {name}")
        return self.values[name]


def load_companies(path: str | Path) -> list[CompanyConfig]:
    config_path = Path(path)
    payload = yaml.safe_load(config_path.read_text())
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("companies.yaml must be a version 1 mapping")
    rows = payload.get("companies")
    if not isinstance(rows, list) or not rows:
        raise ValueError("companies.yaml must contain a nonempty companies list")

    companies: list[CompanyConfig] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or not row.get("company") or not row.get("adapter"):
            raise ValueError("every company needs company and adapter fields")
        name = str(row["company"])
        if name.casefold() in seen:
            raise ValueError(f"duplicate company: {name}")
        seen.add(name.casefold())
        companies.append(CompanyConfig(name, str(row["adapter"]), row))
    return companies
