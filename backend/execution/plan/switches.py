"""스위치 파일 · 확인 코드 · 계획서 4절.

- 스위치 둘(실거래 · 모의) 기본 꺼짐. 파일이 없거나 깨지면 꺼짐.
- 파일은 backend/data/plan_switches.json (.gitignore 의 data/ 로 추적 제외 · 계획서 4-4).
  이 모듈의 set_switch 만 쓴다. 코드 · 스크립트 · 마이그레이션 · 시험은 켜짐을 쓰지 않는다(시험이 막는다).
- 확인 코드: 6자리 · 5분 · 한 코드 5번 틀리면 무효 · 15분에 요청 3번(동작 종류별) · 하루(KST) 실패 10번이면 다음 날까지 잠금.
  저장은 HMAC-SHA256(키 = PLAN_CONFIRM_HMAC_KEY) 만 · 비교는 hmac.compare_digest.
  코드는 알림 기록 · 로그에 남기지 않는다(기록에는 「확인 코드 발송」 제목만).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable, Optional

from sqlalchemy import func, select, update

from .models import PlanConfirmChallenge, PlanEvent, PlanSwitchAudit, utcnow

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_PATH = _PROJECT_ROOT / "backend" / "data" / "plan_switches.json"

SWITCHES = ("live", "paper")
CODE_TTL = timedelta(minutes=5)
MAX_ATTEMPTS = 5
REQUEST_WINDOW = timedelta(minutes=15)
REQUEST_LIMIT = 3            # 구현자 값 (계획서 4-2-1 · 동작 종류별)
DAILY_FAIL_LOCK = 10         # 실거래 켜기와 세 동작을 합쳐 센다
KST = timezone(timedelta(hours=9))

CONFIRM_ACTIONS = ("live_on", "approve", "adopt", "resume", "resolve_order")
ACTION_LABEL = {"live_on": "실거래 켜기", "approve": "계획 승인", "adopt": "보유 인수", "resume": "정지 풀기", "resolve_order": "결과 모르는 주문 확정"}


def switch_path() -> Path:
    raw = os.environ.get("PLAN_SWITCH_PATH")
    return Path(raw) if raw else _DEFAULT_PATH


# ─── 스위치 파일 ──────────────────────────────────────────────

def read_switches(path: Optional[Path] = None) -> dict:
    """{'live': bool, 'paper': bool, ...}. 없거나 깨지거나 값이 bool 이 아니면 해당 칸은 꺼짐."""
    p = path or switch_path()
    out = {"live": False, "paper": False, "changed_at": None, "changed_by": None, "reason": None}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    if not isinstance(raw, dict):
        return out
    for k in SWITCHES:
        out[k] = raw.get(k) is True
    for k in ("changed_at", "changed_by", "reason"):
        v = raw.get(k)
        out[k] = v if isinstance(v, str) else None
    return out


def _write_atomic(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".plan_sw_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


async def set_switch(session, name: str, on: bool, *, actor: str, reason: str = "",
                     path: Optional[Path] = None) -> bool:
    """스위치 한 칸을 바꾸고 감사 표에 남긴다. 이전 값을 돌려준다. 호출 측이 인증 · 코드 확인을 마친 뒤 부른다."""
    if name not in SWITCHES:
        raise ValueError("알 수 없는 스위치")
    p = path or switch_path()
    cur = read_switches(p)
    old = bool(cur[name])
    cur[name] = bool(on)
    cur["changed_at"] = datetime.now(KST).isoformat(timespec="seconds")
    cur["changed_by"] = actor[:40]
    cur["reason"] = reason[:200]
    _write_atomic(p, cur)
    session.add(PlanSwitchAudit(switch=name, old=old, new=bool(on), actor=actor[:40], reason=reason[:200]))
    await session.flush()
    return old


# ─── 확인 코드 ────────────────────────────────────────────────

class ConfirmError(Exception):
    """확인 코드 거부 · reason 은 화면에 보여도 되는 짧은 말."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


def _hmac_key() -> Optional[bytes]:
    from backend.services import config

    k = config.get("PLAN_CONFIRM_HMAC_KEY")
    return k.encode("utf-8") if k else None


def _code_hmac(key: bytes, challenge_id: int, code: str) -> str:
    return hmac.new(key, f"{challenge_id}|{code}".encode("utf-8"), hashlib.sha256).hexdigest()


def content_hash_of(values: dict) -> str:
    """승인 대상 값(가격 · 수량 · 날짜 · 인수 값)의 내용 해시."""
    blob = json.dumps(values, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _kst_midnight_utc_naive(now: datetime) -> datetime:
    now_kst = now.replace(tzinfo=timezone.utc).astimezone(KST)
    mid = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
    return mid.astimezone(timezone.utc).replace(tzinfo=None)


async def daily_fail_count(session, now: Optional[datetime] = None) -> int:
    now = now or utcnow()
    since = _kst_midnight_utc_naive(now)
    n = await session.scalar(
        select(func.count()).select_from(PlanEvent).where(PlanEvent.kind == "confirm_fail", PlanEvent.ts >= since)
    )
    return int(n or 0)


async def is_locked(session, now: Optional[datetime] = None) -> bool:
    return await daily_fail_count(session, now) >= DAILY_FAIL_LOCK


SendFn = Callable[[str, str], Awaitable[bool]]  # (title, body) → 보냈는지


async def request_challenge(
    session, *, action: str, send: SendFn, plan_id: Optional[int] = None,
    revision: Optional[int] = None, content_hash: Optional[str] = None, now: Optional[datetime] = None,
) -> int:
    """새 확인 코드를 만들어 텔레그램으로 즉시 보낸다. challenge_id 를 돌려준다 (코드는 돌려주지 않는다)."""
    if action not in CONFIRM_ACTIONS:
        raise ConfirmError("bad_action", "알 수 없는 동작입니다")
    now = now or utcnow()
    key = _hmac_key()
    if key is None:
        raise ConfirmError("no_key", "확인 코드 비밀값이 설정되지 않아 켤 수 없습니다")
    if await is_locked(session, now):
        raise ConfirmError("locked", "오늘 확인 코드 실패가 너무 많아 내일까지 잠겼습니다")
    recent = await session.scalar(
        select(func.count()).select_from(PlanConfirmChallenge).where(
            PlanConfirmChallenge.action == action, PlanConfirmChallenge.created_at >= now - REQUEST_WINDOW)
    )
    if int(recent or 0) >= REQUEST_LIMIT:
        raise ConfirmError("rate", "15분 안에 코드 요청은 3번까지입니다")

    # 같은 동작 · 같은 계획의 옛 코드는 무효
    await session.execute(
        update(PlanConfirmChallenge)
        .where(PlanConfirmChallenge.action == action, PlanConfirmChallenge.plan_id.is_(plan_id) if plan_id is None
               else PlanConfirmChallenge.plan_id == plan_id,
               PlanConfirmChallenge.used_at.is_(None), PlanConfirmChallenge.invalid_at.is_(None))
        .values(invalid_at=now)
    )
    code = f"{secrets.randbelow(10 ** 6):06d}"
    row = PlanConfirmChallenge(
        action=action, plan_id=plan_id, revision=revision, content_hash=content_hash,
        code_hmac="", created_at=now, expires_at=now + CODE_TTL,
    )
    session.add(row)
    await session.flush()
    row.code_hmac = _code_hmac(key, row.id, code)

    target = f"계획 번호 {plan_id} · 판 {revision}" if plan_id is not None else "계획 없음"
    body = (
        f"동작: {ACTION_LABEL[action]}\n{target}\n"
        f"확인 코드: {code}\n5분 안에 화면에 넣어 주십시오. 본인이 요청하지 않았다면 넣지 마십시오."
    )
    ok = await send("확인 코드 발송", body)
    del code, body
    if not ok:
        row.invalid_at = now
        await session.flush()
        raise ConfirmError("send_failed", "텔레그램으로 코드를 보내지 못했습니다")
    await session.flush()
    return row.id


async def verify_challenge(
    session, *, challenge_id: int, code: str, action: str, plan_id: Optional[int] = None,
    revision: Optional[int] = None, content_hash: Optional[str] = None,
    on_fail: Optional[Callable[[int], Awaitable[None]]] = None, now: Optional[datetime] = None,
) -> None:
    """맞으면 코드를 즉시 무효로 하고 돌려준다. 아니면 ConfirmError.

    틀린 코드 입력만 실패로 센다(만료 · 무효 · 다른 동작은 거부만).
    """
    now = now or utcnow()
    key = _hmac_key()
    if key is None:
        raise ConfirmError("no_key", "확인 코드 비밀값이 설정되지 않았습니다")
    if await is_locked(session, now):
        raise ConfirmError("locked", "오늘 확인 코드 실패가 너무 많아 내일까지 잠겼습니다")
    row = await session.get(PlanConfirmChallenge, challenge_id)
    if row is None:
        raise ConfirmError("invalid", "확인 코드가 유효하지 않습니다")
    if row.action != action or (row.plan_id != plan_id):
        raise ConfirmError("mismatch", "다른 동작 · 다른 계획의 코드입니다")
    if row.used_at is not None or row.invalid_at is not None:
        raise ConfirmError("invalid", "확인 코드가 유효하지 않습니다")
    if now >= row.expires_at:
        raise ConfirmError("expired", "확인 코드가 만료되었습니다 · 새 코드를 받아 주십시오")
    if (row.revision, row.content_hash) != (revision, content_hash):
        row.invalid_at = now
        await session.flush()
        raise ConfirmError("changed", "값이 바뀌었습니다 · 다시 확인해 주십시오")
    expected = _code_hmac(key, row.id, (code or "").strip())
    if not hmac.compare_digest(expected, row.code_hmac):
        row.attempts += 1
        row.fail_count += 1
        if row.attempts >= MAX_ATTEMPTS:
            row.invalid_at = now
        session.add(PlanEvent(plan_id=plan_id, kind="confirm_fail", ts=now, detail=ACTION_LABEL.get(action, action)))
        await session.flush()
        if on_fail is not None:
            await on_fail(row.attempts)
        raise ConfirmError("wrong", "확인 코드가 맞지 않습니다")
    row.used_at = now
    await session.flush()
