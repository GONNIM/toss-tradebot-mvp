"""PrinciplesGate · fail-closed 화이트리스트 게이트 (gate-design-v1 §3-1).

목적: 매수 신호가 PrinciplesRun 최신 PASS 리스트 소속 종목만 실행 진입 허용.
- PASS = 매수 후보 (매수 신호 아님) · 이 게이트는 후보 리스트 소속 검증 관문
- fail-closed: PrinciplesRun 부재/미완료/stale (>26h) 또는 미분류 source → 차단
- 화이트리스트: `sniper` 소스만 우회 (whitelist_bypass 로그)

charter v1.0.9 · gate-design-v1.md §3-1 (2026-08-23 stale 26h 로 수정).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select

from backend.services.db import get_session
from backend.services.models import (
    PrinciplesGateBlockLog,
    PrinciplesResult,
    PrinciplesRun,
    PrinciplesVerificationConfirm,
)

logger = logging.getLogger(__name__)


# ─── 정책 상수 (charter v1.0.9 · 세션 A) ────────────────────
STALE_HOURS = 26  # daily_recompute 23:00 주기 · 24h+2h 여유 · 배치 1회 실패 감지
WHITELIST_SOURCES = frozenset({"sniper"})  # 확장은 charter 절차


@dataclass(frozen=True)
class PrinciplesCheckResult:
    """게이트 판정 결과 (RiskCheckResult 스타일 준수)."""
    passed: bool
    reason: Optional[str] = None     # 차단 사유 코드
    detail: Optional[str] = None     # 사유 상세 (로그·UI용)
    run_id: Optional[int] = None     # 판정에 사용한 run
    bypass: bool = False             # whitelist 우회 여부
    tags: list[str] = field(default_factory=list)  # PASS 종목의 verification_tags


@dataclass(frozen=True)
class VerificationCheckResult:
    """실체 검증 게이트 판정 결과 (gate-design-v1 §3-3)."""
    passed: bool
    reason: Optional[str] = None     # verification_required (미확인) or None (통과)
    detail: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    tags_hash: Optional[str] = None


class PrinciplesGateChecker:
    """PrinciplesGate 판정기.

    사용:
        checker = PrinciplesGateChecker()
        result = await checker.check(ticker="005930", source="super_signal")
        if not result.passed: ...
    """

    async def check(
        self,
        *,
        ticker: str,
        source: str,
    ) -> PrinciplesCheckResult:
        """매수 신호 게이트 판정.

        Args:
          ticker: 신호 대상 종목코드 (6자리)
          source: 신호 소스 (예: super_signal · vip · sniper)

        Returns:
          PrinciplesCheckResult(passed=..., reason=..., detail=..., run_id=..., bypass=...)
        """
        # ① 화이트리스트 우회
        if source in WHITELIST_SOURCES:
            logger.info(
                f"[PrinciplesGate] whitelist_bypass · source={source} · ticker={ticker}"
            )
            # 보완 (2026-08-23) · bypass 이력도 BlockLog 저장 (관측성 · 우회 통로 발동 가시화)
            # reason="whitelist_bypass" 로 block 사유와 구분 · gate-history bypass_24h 카운트.
            try:
                async with get_session() as s:
                    s.add(PrinciplesGateBlockLog(
                        created_at=datetime.now(),
                        ticker=ticker,
                        source=source,
                        reason="whitelist_bypass",
                        detail=f"source={source} in whitelist",
                        run_id=None,
                    ))
                    await s.commit()
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[PrinciplesGate] bypass log 저장 실패 · {exc}")
            return PrinciplesCheckResult(
                passed=True,
                reason="whitelist_bypass",
                detail=f"source={source} in whitelist",
                bypass=True,
            )

        # ② 최신 완료 run 조회 (finished_at NOT NULL · id DESC LIMIT 1)
        async with get_session() as s:
            latest = (await s.execute(
                select(PrinciplesRun)
                .where(PrinciplesRun.finished_at.is_not(None))
                .order_by(PrinciplesRun.id.desc())
                .limit(1)
            )).scalar_one_or_none()

            if latest is None:
                return await self._block(
                    s, ticker, source,
                    reason="principles_run_missing",
                    detail="완료된 principles_runs 없음 (cache_empty_skip 계속 or 배치 미실행)",
                    run_id=None,
                )

            # ③ stale 판정 (finished_at 기준 26h 초과)
            age = datetime.now() - latest.finished_at
            if age > timedelta(hours=STALE_HOURS):
                return await self._block(
                    s, ticker, source,
                    reason="principles_run_stale",
                    detail=f"latest run #{latest.id} finished {age.total_seconds()/3600:.1f}h ago > {STALE_HOURS}h",
                    run_id=latest.id,
                )

            # ④ PASS 리스트 소속 확인
            pass_row = (await s.execute(
                select(PrinciplesResult)
                .where(PrinciplesResult.run_id == latest.id)
                .where(PrinciplesResult.ticker == ticker)
                .where(PrinciplesResult.verdict == "PASS")
            )).scalar_one_or_none()

            if pass_row is None:
                return await self._block(
                    s, ticker, source,
                    reason="principles_fail_closed",
                    detail=f"ticker {ticker} not in PASS list of run #{latest.id}",
                    run_id=latest.id,
                )

            # ⑤ 통과 · verification_tags 로드 (실체 검증 판정용)
            import json as _json
            raw_tags = pass_row.verification_tags
            tags: list[str] = []
            if raw_tags:
                try:
                    tags = list(_json.loads(raw_tags))
                except (ValueError, TypeError):
                    tags = []
            return PrinciplesCheckResult(
                passed=True,
                reason=None,
                detail=None,
                run_id=latest.id,
                bypass=False,
                tags=tags,
            )

    async def _block(
        self,
        session,
        ticker: str,
        source: str,
        reason: str,
        detail: str,
        run_id: Optional[int],
    ) -> PrinciplesCheckResult:
        """차단 로그 기록 + 결과 반환."""
        logger.warning(
            f"[PrinciplesGate] BLOCK · ticker={ticker} · source={source} · "
            f"reason={reason} · run={run_id} · detail={detail}"
        )
        try:
            session.add(PrinciplesGateBlockLog(
                created_at=datetime.now(),
                ticker=ticker,
                source=source,
                reason=reason,
                detail=detail[:290],
                run_id=run_id,
            ))
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[PrinciplesGate] block log 저장 실패 · {exc}")
        return PrinciplesCheckResult(
            passed=False,
            reason=reason,
            detail=detail,
            run_id=run_id,
        )


class VerificationChecker:
    """실체 검증 게이트 (gate-design-v1 §3-3 · 세션 B).

    사용:
        result = await VerificationChecker().check(ticker, tags)
        · tags 없으면 즉시 통과
        · tags 있으면 PrinciplesVerificationConfirm 조회 (ticker, tags_hash 이중키)
          매치 → 통과 · 없음 → verification_required 차단
    """

    async def check(
        self,
        *,
        ticker: str,
        tags: list[str],
    ) -> VerificationCheckResult:
        if not tags:
            return VerificationCheckResult(passed=True)
        from backend.principles.verification_tagger import tags_hash as _hash
        h = _hash(tags)
        async with get_session() as s:
            confirm = (await s.execute(
                select(PrinciplesVerificationConfirm)
                .where(PrinciplesVerificationConfirm.ticker == ticker)
                .where(PrinciplesVerificationConfirm.tags_hash == h)
            )).scalar_one_or_none()
            if confirm is None:
                logger.warning(
                    f"[VerificationGate] BLOCK · ticker={ticker} · tags={tags} · "
                    f"tags_hash={h} · reason=verification_required · 사용자 확인 필요"
                )
                return VerificationCheckResult(
                    passed=False,
                    reason="verification_required",
                    detail=f"태그 {tags} 미확인 · POST /api/v1/principles/verification/confirm 필요",
                    tags=tags,
                    tags_hash=h,
                )
            logger.info(
                f"[VerificationGate] 확인 유지 · ticker={ticker} · tags={tags} · "
                f"confirmed_at={confirm.confirmed_at}"
            )
            return VerificationCheckResult(
                passed=True,
                tags=tags,
                tags_hash=h,
            )


# 프로세스 lifetime 싱글턴
_checker: Optional[PrinciplesGateChecker] = None
_verifier: Optional[VerificationChecker] = None


def get_principles_gate() -> PrinciplesGateChecker:
    global _checker
    if _checker is None:
        _checker = PrinciplesGateChecker()
    return _checker


def reset_principles_gate() -> None:
    """테스트·재구성용."""
    global _checker, _verifier
    _checker = None
    _verifier = None


def get_verification_checker() -> VerificationChecker:
    global _verifier
    if _verifier is None:
        _verifier = VerificationChecker()
    return _verifier
