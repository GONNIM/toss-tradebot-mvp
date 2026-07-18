"""3차 리뷰 P2 마이그레이션 · powderkeg_financial_snapshot 3 컬럼 추가.

추가 컬럼:
- contract_liabilities  REAL      · 계약부채 (수주산업 조정 net_cash · P2-4)
- is_delisted           INTEGER   · 상폐 여부 (PIT 층화 백테스트 · P2-2)
- delisted_at           TEXT      · 상폐 일자 YYYY-MM-DD

alembic 미도입 상태 · sqlite ALTER TABLE 직접 실행.
서버 postgres 승격 시 별도 스크립트 필요.

실행 (서버 SSH):
  ssh root@optimus8.cafe24.com
  cd /root/toss-tradebot-mvp/backend
  .venv/bin/python scripts/migrations/2026-07-17-p2-contract-liab-delisted.py

멱등 · 이미 컬럼 있으면 SKIP.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

# 기본: backend/../data/tradebot.db
DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "tradebot.db"


def _db_path() -> Path:
    """DATABASE_URL env 우선 · 없으면 기본 경로."""
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("sqlite"):
        # sqlite:///path 또는 sqlite+aiosqlite:///path
        raw = url.split("///", 1)[1]
        return Path(raw).resolve()
    return DEFAULT_DB


STATEMENTS = [
    ("contract_liabilities",
     "ALTER TABLE powderkeg_financial_snapshot ADD COLUMN contract_liabilities REAL"),
    ("is_delisted",
     "ALTER TABLE powderkeg_financial_snapshot ADD COLUMN is_delisted INTEGER DEFAULT 0"),
    ("delisted_at",
     "ALTER TABLE powderkeg_financial_snapshot ADD COLUMN delisted_at TEXT"),
]


def main() -> None:
    db = _db_path()
    if not db.exists():
        raise SystemExit(f"DB not found: {db}")
    print(f"DB · {db}")
    conn = sqlite3.connect(str(db))
    cur = conn.cursor()

    # 현재 컬럼 조회 (멱등 판정용)
    cur.execute("PRAGMA table_info(powderkeg_financial_snapshot)")
    existing = {row[1] for row in cur.fetchall()}
    print(f"existing columns · {len(existing)}")

    for col, stmt in STATEMENTS:
        if col in existing:
            print(f"SKIP (already exists) · {col}")
            continue
        try:
            cur.execute(stmt)
            print(f"OK  · added {col}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                print(f"SKIP (duplicate) · {col}")
            else:
                raise

    conn.commit()
    conn.close()
    print("done.")


if __name__ == "__main__":
    main()
