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
