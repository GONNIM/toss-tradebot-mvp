"""WP55 · 최소 열람 페이지 (3탭 md 렌더 · biotech 이름공간 · 기존 메뉴 무수정).

실행: `backend/venv/bin/python -m backend.scripts.biotech_h55_viewer` → http://localhost:4000/
포트 변경: `BIOTECH_VIEWER_PORT=8080` 환경변수 (기본 4000 · WP67-2 · 2026-09-14)

3탭:
- /radar   → docs/plans/biotech/watchlist/radar-v1.3-*.md 중 최신
- /rumor   → docs/plans/biotech/rumor-daily/*.md (날짜 선택)
- /map     → docs/plans/biotech/STATUS.md

- 상단 GLOSSARY 링크 · 하단 고정 문구 (알파 미확정 · 소액 전향용 · 자동매매 없음)
- 반자동 티켓 탭은 Phase C 1순위 보류함 (안내만)
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging

import glob
import os
import re
from pathlib import Path

import markdown as md_lib
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BIOTECH_DOCS = PROJECT_ROOT / "docs" / "plans" / "biotech"

app = FastAPI(title="Biotech Catalyst Radar · Viewer", docs_url=None, redoc_url=None)


HEADER = """
<!doctype html>
<html><head><meta charset="utf-8"><title>Biotech Catalyst Radar</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:1000px;margin:24px auto;padding:0 16px;color:#222;line-height:1.6}
nav{background:#f4f6fa;padding:12px 16px;border-radius:8px;margin-bottom:16px;display:flex;gap:16px;flex-wrap:wrap;align-items:center}
nav a{color:#0366d6;text-decoration:none;font-weight:600}
nav a:hover{text-decoration:underline}
nav .sep{color:#999}
.footer{margin-top:32px;padding:12px 16px;background:#fff4e6;border-left:4px solid #f9a826;border-radius:4px;font-size:14px}
table{border-collapse:collapse;width:100%;margin:12px 0}
th,td{border:1px solid #e1e4e8;padding:8px 12px;text-align:left}
th{background:#f6f8fa}
code{background:#f6f8fa;padding:2px 6px;border-radius:3px;font-size:0.9em}
h1{border-bottom:2px solid #e1e4e8;padding-bottom:8px}
h2{border-bottom:1px solid #e1e4e8;padding-bottom:6px;margin-top:32px}
blockquote{border-left:4px solid #dfe2e5;color:#6a737d;padding:0 16px;margin:0 0 16px}
select{padding:6px 10px;border-radius:4px;border:1px solid #d0d7de}
</style></head><body>
<nav>
<a href="/radar">📡 레이더 순위표</a>
<span class="sep">·</span>
<a href="/rumor">🗣️ 소문 확인</a>
<span class="sep">·</span>
<a href="/map">🗺️ 가능성 지도</a>
<span class="sep">·</span>
<a href="/glossary">📖 용어집</a>
<span class="sep">·</span>
<a href="/phase-a-final">📄 Phase A 최종</a>
</nav>
"""

FOOTER = """
<div class="footer">
⚠️ <b>알파 (초과 수익) 미확정 · 소액 전향용 · 매수 신호 아님</b> · 자동매매 없음 · 반자동 티켓 탭 (매수 확인 버튼) 은 Phase C 1순위 보류함 · 임시 기록 = <code>backend/data/biotech/trades/trades_manual.csv</code> 수동 CSV
</div>
</body></html>
"""


def render_md(md_path: Path, title_prefix: str = "") -> str:
    if not md_path.exists():
        raise HTTPException(404, f"파일 없음: {md_path}")
    md_text = md_path.read_text()
    html = md_lib.markdown(md_text, extensions=["tables", "fenced_code"])
    return HEADER + f"<div class='content'>{html}</div>" + FOOTER


@app.get("/", response_class=HTMLResponse)
def index():
    return HEADER + """
    <h1>Biotech Catalyst Radar · 열람 (로컬)</h1>

    <h2>확인 순서 5줄 (WP67-2 · 2026-09-14)</h2>
    <ol>
      <li><b>① 순위표</b>: <a href="/radar">📡 레이더</a> · 오늘 상위 30 (뉴스 예정일 임박순 · 이유 병기)</li>
      <li><b>② 소문 확인</b>: <a href="/rumor">🗣️ rumor daily</a> · 표 1 (살 자리) · 표 2 (뉴스 통과) · 표 3 (언급 있음 원값) · 표 4 (임원·대주주 매수 · 유보 pending)</li>
      <li><b>③ 상태판 결론 4줄</b>: <a href="/map">🗺️ STATUS</a> · 오늘 알아낸 것 5줄 (H1b/H8 검정 3/WP54-3/F4 유보)</li>
      <li><b>④ 용어집</b>: <a href="/glossary">📖 GLOSSARY</a> · 코드·상태·가설 뜻</li>
      <li><b>⑤ crontab</b>: 터미널에서 <code>crontab -l | grep biotech</code> · 2줄 (daily · forward) 확인</li>
    </ol>

    <h2>추가 링크</h2>
    <ul>
      <li><a href="/phase-a-final">📄 Phase A 최종 (2026-09-14 종결본)</a></li>
      <li>날짜별 소문: <a href="/rumor?date=2026-09-14">/rumor?date=2026-09-14</a></li>
    </ul>

    <p><b>종료 명령</b>: 터미널에서 <code>backend/scripts/biotech_local.sh stop</code></p>
    """ + FOOTER


@app.get("/radar", response_class=HTMLResponse)
def radar():
    matches = sorted(glob.glob(str(BIOTECH_DOCS / "watchlist" / "radar-v1.3-*.md")))
    if not matches:
        raise HTTPException(404, "radar md 없음")
    return render_md(Path(matches[-1]))


@app.get("/rumor", response_class=HTMLResponse)
def rumor(date: str | None = None):
    files = sorted(glob.glob(str(BIOTECH_DOCS / "rumor-daily" / "*.md")))
    if not files:
        raise HTTPException(404, "rumor daily md 없음")
    dates = [Path(f).stem for f in files if re.match(r"\d{4}-\d{2}-\d{2}", Path(f).stem)]
    dates.sort(reverse=True)
    pick = date or dates[0]
    target = BIOTECH_DOCS / "rumor-daily" / f"{pick}.md"
    if not target.exists():
        raise HTTPException(404, f"{pick} 파일 없음")
    selector = "<form method='get'><select name='date' onchange='this.form.submit()'>"
    for d in dates:
        sel = " selected" if d == pick else ""
        selector += f"<option value='{d}'{sel}>{d}</option>"
    selector += "</select></form>"
    md_text = target.read_text()
    html = md_lib.markdown(md_text, extensions=["tables", "fenced_code"])
    return HEADER + f"<p>날짜 선택: {selector}</p>" + f"<div class='content'>{html}</div>" + FOOTER


@app.get("/map", response_class=HTMLResponse)
def map_view():
    return render_md(BIOTECH_DOCS / "STATUS.md")


@app.get("/glossary", response_class=HTMLResponse)
def glossary():
    return render_md(BIOTECH_DOCS / "GLOSSARY.md")


@app.get("/phase-a-final", response_class=HTMLResponse)
def phase_a_final():
    return render_md(BIOTECH_DOCS / "PHASE-A-FINAL.md")


def main():
    require_secure_logging()
    import uvicorn
    port = int(os.environ.get("BIOTECH_VIEWER_PORT", "4000"))
    print(f"Biotech Catalyst Radar Viewer → http://localhost:{port}/")
    print("  / · /radar · /rumor · /map · /glossary · /phase-a-final")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
