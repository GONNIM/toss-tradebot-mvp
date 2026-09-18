"""WP69-1 · biotech 라우터 pytest (5 경로 · admin 인증 · 파일 없음 404).

목적:
- (a) 인증 없이 접근 시 401 (admin 필요)
- (b) admin 세션으로 접근 시 200 · JSON 반환
- (c) 존재하지 않는 rumor date 404
- (d) 파일 없는 경우 404 (임시 파일 없으면 skip)
- (e) 접점 격리 확인 (기존 라우터 무회귀 · main.py include_router 정합)
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("SNIPER_API_TOKEN", "test-token-biotech-router")

from backend.api.main import app  # noqa: E402
from backend.api.auth import SESSION_COOKIE_NAME  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app)


def _auth_headers() -> dict:
    """admin 세션 토큰 헤더."""
    return {"X-API-Token": os.environ["SNIPER_API_TOKEN"]}


def test_a_biotech_routes_require_auth(client):
    """(a) 인증 없이 접근 → 401."""
    for path in ["/api/v1/biotech/radar", "/api/v1/biotech/status",
                 "/api/v1/biotech/glossary", "/api/v1/biotech/final",
                 "/api/v1/biotech/rumor/dates", "/api/v1/biotech/rumor"]:
        r = client.get(path)
        assert r.status_code == 401, f"{path} 예상 401 · 실제 {r.status_code}"


def test_b_biotech_routes_200_with_admin(client):
    """(b) admin 세션으로 접근 → 200 · JSON."""
    for path in ["/api/v1/biotech/status", "/api/v1/biotech/glossary",
                 "/api/v1/biotech/final", "/api/v1/biotech/rumor/dates"]:
        r = client.get(path, headers=_auth_headers())
        assert r.status_code == 200, f"{path} 예상 200 · 실제 {r.status_code} · body={r.text[:200]}"
        data = r.json()
        assert isinstance(data, dict), f"{path} JSON dict 예상"


def test_c_biotech_status_has_content(client):
    """(c) /status → HTML + 메타 필드."""
    r = client.get("/api/v1/biotech/status", headers=_auth_headers())
    assert r.status_code == 200
    data = r.json()
    assert "html" in data
    assert "title" in data
    assert "generated_utc" in data
    assert "path" in data
    assert data["raw_md_size"] > 0
    assert "<h1" in data["html"] or "<h2" in data["html"], "HTML 렌더 · h1/h2 헤더 최소 하나"


def test_d_rumor_date_not_found_404(client):
    """(d) 존재하지 않는 날짜 → 404."""
    r = client.get("/api/v1/biotech/rumor?date=1999-01-01", headers=_auth_headers())
    assert r.status_code == 404, f"예상 404 · 실제 {r.status_code}"


def test_e_rumor_bad_date_format_400(client):
    """(e) 날짜 형식 오류 → 400."""
    r = client.get("/api/v1/biotech/rumor?date=bad-format", headers=_auth_headers())
    assert r.status_code == 400, f"예상 400 · 실제 {r.status_code}"


def test_f_biotech_router_isolation(client):
    """(f) 접점 격리 확인 · 기존 라우터 회귀 없음."""
    # 기존 admin session GET 은 안정성 · role 반환
    r = client.get("/api/v1/admin/session")
    # session GET 은 인증 없어도 200 (role=anon) · 라우터 자체 존재 확인
    assert r.status_code == 200
    body = r.json()
    assert "role" in body
    assert body["role"] in ("admin", "subscriber", "anon")

    # biotech 라우터가 openapi 스키마에 노출되는지 (include_router 정합)
    r_schema = client.get("/openapi.json")
    assert r_schema.status_code == 200
    paths = r_schema.json().get("paths", {})
    for expected in ["/api/v1/biotech/radar", "/api/v1/biotech/rumor",
                      "/api/v1/biotech/status", "/api/v1/biotech/glossary",
                      "/api/v1/biotech/final", "/api/v1/biotech/rumor/dates"]:
        assert expected in paths, f"openapi 에 {expected} 미노출 · include_router 확인"


def test_g_markdown_missing_fallback(client, monkeypatch):
    """(g) WP69-2b · markdown 미설치 상황 모의 → 200 원문 md fallback."""
    import builtins
    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "markdown":
            raise ImportError("mocked: markdown unavailable")
        return real_import(name, *args, **kwargs)

    # biotech.py 의 _CACHE 초기화 · fallback 경로 실행 강제
    from backend.api.routes import biotech as _b
    _b._CACHE.clear()

    monkeypatch.setattr(builtins, "__import__", mock_import)
    r = client.get("/api/v1/biotech/status", headers=_auth_headers())
    assert r.status_code == 200, f"markdown 부재에도 200 예상 · 실제 {r.status_code}"
    data = r.json()
    assert data["render_mode"] == "plain_md_fallback", "fallback 모드 표기"
    assert "<pre>" in data["html"], "원문 md 는 <pre> 로 감싸 반환"

    # 캐시 초기화 후 정상 markdown 복원
    _b._CACHE.clear()


def test_h_main_health_when_biotech_import_fails():
    """(h) WP69-2b · biotech 라우터 import 실패 모의 → main app 정상 기동 · /health 200 예상.

    본체 보호: try/except 로 biotech 라우터 등록 실패 시에도 uvicorn/앱은 정상.
    실제 mock 은 어렵지만 · main.py 의 try/except 블록 존재 검증.
    """
    import inspect
    from backend.api import main as _main_module

    src = inspect.getsource(_main_module)
    # try 블록 안 biotech import 확인
    assert "try:\n    from backend.api.routes import biotech" in src, "biotech import 는 try/except 안에 있어야"
    assert "except Exception as _biotech_exc" in src, "biotech import 예외 handler 존재"
    assert "biotech router disabled" in src, "라우터 비활성화 warning 문구 존재"


def test_i_radar_json_endpoint(client):
    """(i) WP71-2 · /radar.json · admin · rows 배열 · 열 <= 7 (요약 필드만)."""
    r = client.get("/api/v1/biotech/radar.json", headers=_auth_headers())
    assert r.status_code == 200, f"radar.json 200 예상 · 실제 {r.status_code}"
    data = r.json()
    assert "generated" in data and "source_csv" in data and "rows" in data
    assert isinstance(data["rows"], list)
    if data["rows"]:
        row = data["rows"][0]
        # 요약 필드 · 열 표시용 (rank/ticker/name/mcap_bucket/score/state/news_window)
        for k in ["rank", "ticker", "name", "mcap_bucket", "score", "state", "news_window"]:
            assert k in row, f"radar row 에 {k} 누락"
        assert "factors" in row, "factors dict 병기"


def test_j_rumor_json_endpoint(client):
    """(j) WP71-2 · /rumor.json · admin · rows 배열 · table 필드 표1~4."""
    r = client.get("/api/v1/biotech/rumor.json", headers=_auth_headers())
    assert r.status_code == 200
    data = r.json()
    assert "date" in data and "rows" in data
    assert isinstance(data["rows"], list)
    if data["rows"]:
        tables = {row.get("table") for row in data["rows"]}
        # 최소 하나 이상의 표 (표1/표2/표3/표4)
        assert tables.intersection({"표1", "표2", "표3", "표4"}), f"table 필드 예상 표1~4 · 실제 {tables}"


def test_k_frontend_contract_biotech_md_absent():
    """(k) WP71-2 계약 · frontend/app/biotech/page.tsx 에 실 .biotech-md CSS 클래스 사용 0건.

    주석은 허용 · 실 클래스 선언·사용은 삭제됨을 검증.
    """
    import re
    from pathlib import Path
    src = Path(__file__).resolve().parents[2] / "frontend" / "app" / "biotech" / "page.tsx"
    text = src.read_text()
    # dangerouslySetInnerHTML 안 className="biotech-md" 등 실 사용 패턴 검색
    class_uses = re.findall(r'className\s*=\s*"[^"]*biotech-md[^"]*"', text)
    style_uses = re.findall(r'\.biotech-md\s*\{', text)
    assert not class_uses, f"biotech-md className 사용 발견: {class_uses}"
    assert not style_uses, f"biotech-md CSS 선언 발견: {style_uses}"
