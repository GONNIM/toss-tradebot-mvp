"""DB 초기화 스크립트.

사용:
    cd backend && python -m scripts.init_db

첫 실행 시 backend/data/tradebot.db 생성.
이미 존재하면 기존 테이블 유지 (create_all 은 idempotent).
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path


async def main() -> None:
    """모든 테이블 생성."""
    # backend/data/ 디렉터리 존재 보장
    data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    from backend.services.db import init_db

    print("📦 Initializing SQLite database...")
    print(f"   DATABASE_URL = {os.environ.get('DATABASE_URL', 'sqlite+aiosqlite:///./data/tradebot.db')}")

    await init_db()

    # 생성된 테이블 목록 출력
    from backend.services.models import Base
    table_names = sorted(Base.metadata.tables.keys())
    print(f"\n✅ {len(table_names)} tables created:")
    for name in table_names:
        print(f"   - {name}")


if __name__ == "__main__":
    asyncio.run(main())
