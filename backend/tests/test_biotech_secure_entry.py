"""WP8 · biotech 스크립트 자격증명 보안 구조 검사.

- 모든 backend/scripts/biotech_*.py 파일에 `from backend.services import config` 존재 검사
- main() 을 가진 파일은 `require_secure_logging()` 호출 존재 검사
- _biotech_bootstrap 은 자체 검사 대상 아님 (인프라)

배경 (2026-09-08 · DART_API_KEY 4차 노출):
- WP3 신규 스크립트 biotech_h5_glp1_map.py 가 config 미경유 · httpx INFO 로 키 노출
- 재발 방지 = 테스트로 강제 (신규 스크립트 추가 시 CI 실패)

WP23 (2026-09-09) · SEC 지정 헤더 형식 검사 추가.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"

# 예외 (인프라 · main 없음)
EXEMPT = {"_biotech_bootstrap.py", "__init__.py"}


def _biotech_files() -> list[Path]:
    return [
        p
        for p in SCRIPT_DIR.glob("biotech_*.py")
        if p.name not in EXEMPT
    ]


@pytest.mark.parametrize("path", _biotech_files(), ids=lambda p: p.name)
def test_biotech_script_imports_config(path: Path) -> None:
    text = path.read_text()
    assert "from backend.services import config" in text, (
        f"{path.name}: 'from backend.services import config' 미존재 · "
        "자격증명 마스킹 필터 미로드 위험 (WP8 · 2026-09-08 DART 4차 재발 대응)"
    )
    assert "from backend.scripts._biotech_bootstrap import require_secure_logging" in text, (
        f"{path.name}: bootstrap import 미존재"
    )


def test_sec_ua_matches_designated_format() -> None:
    """WP23 · SEC 웹 그룹 회신 지정 형식: "회사명 연락처이메일" (버전·괄호 없음)."""
    from backend.scripts.biotech_sec_common import SEC_UA
    pattern = re.compile(r"^[A-Za-z0-9 ]+ [^\s@]+@[^\s@]+$")
    assert pattern.match(SEC_UA), (
        f"SEC_UA={SEC_UA!r} · 지정 형식 미준수 · '회사명 이메일' (버전·괄호 없음)"
    )


def test_sec_accept_encoding_exact_value() -> None:
    """WP23 · Accept-Encoding 값 고정 · 'gzip, deflate'."""
    from backend.scripts.biotech_sec_common import SEC_ACCEPT_ENCODING
    assert SEC_ACCEPT_ENCODING == "gzip, deflate", (
        f"SEC_ACCEPT_ENCODING={SEC_ACCEPT_ENCODING!r} · 지정 값 'gzip, deflate' 필수"
    )


def test_sec_from_is_email() -> None:
    from backend.scripts.biotech_sec_common import SEC_FROM
    assert re.match(r"^[^\s@]+@[^\s@]+$", SEC_FROM), (
        f"SEC_FROM={SEC_FROM!r} · 이메일 형식 필수"
    )


def test_httpx_auto_decompresses_gzip_response() -> None:
    """WP23 · httpx 응답 자동 압축 해제 확인 (Accept-Encoding gzip, deflate 요구 규정).

    httpx 는 요청 헤더에 Accept-Encoding 지정 시 응답 Content-Encoding 을 자동 해제해
    Response.text/.json() 에는 이미 디코딩된 payload 를 제공한다.
    """
    import gzip

    import httpx

    payload = b'{"ok": true, "note": "wp23 fixture"}'
    gz = gzip.compress(payload)

    def handler(request: httpx.Request) -> httpx.Response:
        # 요청 헤더에 지정 형식이 실제로 실려 나가는지 확인
        assert request.headers.get("Accept-Encoding") == "gzip, deflate"
        return httpx.Response(
            200,
            headers={
                "Content-Encoding": "gzip",
                "Content-Type": "application/json",
            },
            content=gz,
        )

    from backend.scripts.biotech_sec_common import SEC_ACCEPT_ENCODING
    transport = httpx.MockTransport(handler)
    with httpx.Client(
        transport=transport,
        headers={"Accept-Encoding": SEC_ACCEPT_ENCODING},
    ) as client:
        r = client.get("https://data.sec.gov/mock")
        # 자동 해제 확인 (raw bytes 는 여전히 gzip 이지만 .text 는 디코딩됨)
        assert r.json() == {"ok": True, "note": "wp23 fixture"}


@pytest.mark.parametrize("path", _biotech_files(), ids=lambda p: p.name)
def test_biotech_script_main_calls_require(path: Path) -> None:
    text = path.read_text()
    if "def main(" not in text:
        pytest.skip("main() 없음 (공용 유틸)")
    # main() 정의 이후 require_secure_logging() 호출이 존재하는지
    main_idx = text.find("def main(")
    tail = text[main_idx:]
    # 다음 top-level def 까지만 검사 (main() 내부)
    end_idx = tail.find("\nif __name__", 1)
    if end_idx == -1:
        end_idx = len(tail)
    main_body = tail[:end_idx]
    assert "require_secure_logging()" in main_body, (
        f"{path.name}: main() 첫 부분에 require_secure_logging() 호출 미존재"
    )
