"""Lambda起動時の環境変数読込(fail-fast)。"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    table_name: str


def get_config() -> Config:
    table_name = os.environ.get("TABLE_NAME")
    if not table_name:
        raise RuntimeError("TABLE_NAME environment variable is required")
    return Config(table_name=table_name)
