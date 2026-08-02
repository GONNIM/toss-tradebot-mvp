"""Serenity per-ticker seed CLI · Phase L4 · 2026-08-02.

사용:
    python -m backend.scripts.serenity_seed_tiers          # SEED 적용 + refresh
    python -m backend.scripts.serenity_seed_tiers -v       # DEBUG 로그
"""
from __future__ import annotations

from backend.discovery.serenity.seed_tiers import main

if __name__ == "__main__":
    raise SystemExit(main())
