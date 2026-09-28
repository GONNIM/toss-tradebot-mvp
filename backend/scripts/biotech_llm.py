"""WP77-2 · 급등 브리핑 자동 요약 (z.ai) · 모델 선택 + 요약 + 출력 검증.

원칙 (사용자 지시 · 사전 고정):
- 입력 = WP77-1 브리핑 패널 자료만 (번호 붙은 출처 목록) · 그 밖의 지식 사용 금지 (프롬프트 고정)
- 출력 = 한국어 3줄 이내 · 문장마다 출처 번호 [1][2]… 필수
- 코드 검증: 출처 번호가 없거나 범위 밖이면 그 문장 폐기 · 권유·전망 금지어가 있으면 그 문장 폐기
- 키 = config 로더가 읽은 환경변수 ZAI_API_KEY · 요청 헤더로만 전달 · 로그·예외 메시지에 키 미포함
- 매 호출 로그에 선택된 모델 이름 기록 (키 아님)

모델 선택 resolve_zai_model() (사전 고정 · 3단계):
  ① 환경변수 ZAI_MODEL 이 있으면 사용
  ② 없거나 비면 z.ai 모델 목록 API 조회 → 제공자가 기본·권장으로 표시한 모델 · 표시가 없으면 목록의 첫 정식 (비실험) 모델
  ③ 조회 실패 시 코드 기본값 상수 ZAI_MODEL_FALLBACK (이 파일에만 존재)
  목록 조회 결과는 하루 1회 캐시 (KST 날짜 기준)
"""
from __future__ import annotations

from backend.services import config  # noqa: F401 · .env 로드 (키는 환경변수로만)
from backend.scripts._biotech_bootstrap import require_secure_logging

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

from backend.scripts import _biotech_paths as _P

LOG = logging.getLogger("biotech_llm")

ZAI_BASE_URL = "https://api.z.ai/api/paas/v4"   # z.ai OpenAI 호환 (backend/services/llm.py 와 같은 주소)
ZAI_MODEL_FALLBACK = "glm-4.6"                  # ③ 마지막 수단 · 2026-09-28 목록에 존재 확인
TIMEOUT_SEC = 20.0
MAX_LINES = 3
_EXPERIMENTAL_RE = re.compile(r"preview|exp|beta|alpha|test|dev", re.IGNORECASE)
_DEFAULT_FLAG_KEYS = ("default", "is_default", "recommended", "is_recommended")

# 권유·전망 금지어 (문장 폐기) · 사실 서술 ("임원 매수 신고") 은 허용되도록 권유·예측 형태만
FORBIDDEN_RE = re.compile(
    r"매수하|매도하|매수를 권|매도를 권|사세요|파세요|사야|팔아야|추천|권유|권장|목표가|목표 주가|주가 전망|전망|"
    r"오를 것|내릴 것|상승할|하락할|급등할|급락할|오를 가능성|수익을 기대|기대 수익|"
    r"\bbuy\b|\bsell\b|price target|outperform|underperform|upside|downside",
    re.IGNORECASE,
)
_CITE_RE = re.compile(r"\[(\d+)\]")

SYSTEM_PROMPT = (
    "너는 수집된 사실을 한국어로 짧게 정리하는 도구다. 규칙:\n"
    "1) 아래 번호 붙은 자료에 적힌 내용만 쓴다. 자료에 없는 사실·배경지식·추측을 쓰지 않는다.\n"
    "2) 최대 3줄. 한 줄에 한 문장. 문장 끝마다 근거 자료 번호를 [1] 처럼 붙인다.\n"
    "3) 매수·매도 권유, 주가 전망, 목표가, 추천 표현을 쓰지 않는다.\n"
    "4) 자료가 부족하면 '자료 부족' 한 줄만 쓰지 말고, 있는 사실만 적는다.\n"
    "5) 줄 앞에 기호나 번호 목록을 붙이지 않는다.\n"
    "6) 자료에 적힌 출처 이름 (apewisdom · 레딧 · SEC 8-K · Form 4) 을 바꾸거나 섞지 않고 그대로 쓴다."
)


# ── 모델 선택 ──────────────────────────────────────────────────

def _kst_today() -> str:
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")


def _pick_from_list(items: list[dict]) -> str | None:
    """제공자 표시 (기본·권장) 우선 · 없으면 첫 정식 (비실험) 모델."""
    for it in items:
        if any(bool(it.get(k)) for k in _DEFAULT_FLAG_KEYS):
            return str(it.get("id") or "") or None
    for it in items:
        mid = str(it.get("id") or "")
        if mid and not _EXPERIMENTAL_RE.search(mid):
            return mid
    return None


def resolve_zai_model(
    fetch_models: Callable[[], list[dict]] | None = None,
    cache_path: Path | None = None,
    today: str | None = None,
) -> tuple[str, str]:
    """(모델 이름, 선택 근거) · 근거 = env | list | list_cache | fallback."""
    env = (os.environ.get("ZAI_MODEL") or "").strip()
    if env:
        return env, "env"
    today = today or _kst_today()
    cache_path = cache_path or (_P.out_dir("briefs") / "zai_models_cache.json")
    try:
        if cache_path.exists():
            c = json.loads(cache_path.read_text())
            if c.get("date") == today and c.get("model"):
                return c["model"], "list_cache"
    except Exception:
        pass
    try:
        items = (fetch_models or _fetch_models)()
        picked = _pick_from_list(items)
        if picked:
            cache_path.write_text(json.dumps({"date": today, "model": picked, "n": len(items)}))
            return picked, "list"
    except Exception as e:  # 조회 실패 → ③
        LOG.warning("z.ai 모델 목록 조회 실패 · %s", e.__class__.__name__)
    return ZAI_MODEL_FALLBACK, "fallback"


def _headers() -> dict[str, str]:
    key = (os.environ.get("ZAI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("ZAI_API_KEY 미설정")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _fetch_models() -> list[dict]:
    r = httpx.get(f"{ZAI_BASE_URL}/models", headers=_headers(), timeout=TIMEOUT_SEC)
    if r.status_code in (403, 429):
        raise RuntimeError(f"z.ai models HTTP {r.status_code}")
    r.raise_for_status()
    return r.json().get("data", [])


# ── 출력 검증 ──────────────────────────────────────────────────

def validate_lines(text: str, n_sources: int) -> tuple[list[str], list[dict]]:
    """(통과 문장, 폐기 기록) · 출처 번호 없음/범위 밖 · 금지어 → 폐기 · 최대 3줄."""
    kept: list[str] = []
    dropped: list[dict] = []
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("-•*·0123456789.) ").strip()
        if not line:
            continue
        cites = [int(x) for x in _CITE_RE.findall(line)]
        if not cites or any(c < 1 or c > n_sources for c in cites):
            dropped.append({"reason": "no_or_bad_citation", "line": line[:200]})
            continue
        if FORBIDDEN_RE.search(line):
            dropped.append({"reason": "forbidden_word", "line": line[:200]})
            continue
        kept.append(line)
    return kept[:MAX_LINES], dropped


def build_user_prompt(ticker: str, sources: list[str]) -> str:
    body = "\n".join(f"[{i}] {s}" for i, s in enumerate(sources, 1))
    return f"종목 {ticker} 에 대해 수집된 자료:\n{body}\n\n위 자료만으로 3줄 이내로 정리하라."


def summarize(ticker: str, sources: list[str], post: Callable[[str, dict], dict] | None = None) -> dict[str, Any]:
    """요약 1건 · 실패 시 {'ok': False} (패널만 표시)."""
    model, how = resolve_zai_model()
    LOG.info("z.ai 요약 호출 · ticker=%s · model=%s (%s)", ticker, model, how)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(ticker, sources)},
        ],
        "temperature": 0.1,
        "max_tokens": 800,
        # glm-5.x 는 추론 모드 기본 · 추론이 토큰을 소진해 본문이 잘리는 사례 (2026-09-28 ENTX "레" 한 글자) → 끔
        "thinking": {"type": "disabled"},
    }
    try:
        data = (post or _post)(f"{ZAI_BASE_URL}/chat/completions", payload)
        text = data["choices"][0]["message"]["content"]
    except Exception as e:
        LOG.warning("z.ai 요약 실패 · ticker=%s · %s", ticker, e.__class__.__name__)
        return {"ok": False, "model": model, "model_source": how, "error": e.__class__.__name__}
    kept, dropped = validate_lines(text, len(sources))
    return {"ok": bool(kept), "model": model, "model_source": how, "lines": kept, "dropped": dropped}


def _post(url: str, payload: dict) -> dict:
    r = httpx.post(url, headers=_headers(), json=payload, timeout=TIMEOUT_SEC)
    if r.status_code in (403, 429):
        raise RuntimeError(f"z.ai HTTP {r.status_code}")
    r.raise_for_status()
    return r.json()


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    model, how = resolve_zai_model()
    print(json.dumps({"model": model, "source": how}, ensure_ascii=False))


if __name__ == "__main__":
    main()
