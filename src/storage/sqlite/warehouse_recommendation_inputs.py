# 为仓库建议读取与评分相关的账号指纹，不将战报或无关 UI 写入视作输入变化。
from __future__ import annotations

from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3


def recommendation_account_identity(path: Path) -> str:
    with closing(sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)) as db:
        db.execute("BEGIN")
        names = sorted(
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if row[0] not in {"character_instance_mapping", "character_profile_observation"}
            and row[0].startswith(
                ("character_", "custom_character", "optimization_preference", "loadout_plan", "role_loadout_slot")
            )
        )
        digest = sha256()
        for name in names:
            # 表名来自 SQLite schema；值以排序后的序列冻结，不依赖查询默认顺序。
            quoted = '"' + name.replace('"', '""') + '"'
            columns = [r[1] for r in db.execute("PRAGMA table_info(" + quoted + ")") if not r[1].endswith("_at_utc")]
            projection = ",".join('"' + c.replace('"', '""') + '"' for c in columns)
            rows = sorted(
                json.dumps(row, ensure_ascii=False, default=str)
                for row in db.execute("SELECT " + projection + " FROM " + quoted)
            )
            digest.update(json.dumps([name, rows], ensure_ascii=False).encode("utf-8"))
        return digest.hexdigest()
