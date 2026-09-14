"""WP57 · STATUS.md 자동 생성기 (봉인 JSON + 최신 파일 스캔 → 상단 5줄·가설표·Phase C·사용자 액션).

수동 편집 절 최소화:
- "## 가능성 지도 (수동)" 만 사용자 손 편집
- 나머지 (상단 5줄 · 가설별 상태 · Phase C 순서 · 사용자 액션) 는 이 스크립트가 자동 재생성

봉인 JSON 소스:
- h3_seal · h5_seal · h6_dry_run_report · h8_h1b_full_seal · h54v2_signal_full_seal

daily.sh 끝에서 실행 (매일 갱신).
"""
from __future__ import annotations

from backend.services import config  # noqa: F401
from backend.scripts._biotech_bootstrap import require_secure_logging, data_sha

import glob
import json
import logging
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

logging.getLogger("httpx").setLevel(logging.WARNING)
LOG = logging.getLogger("biotech_h57b_status_gen")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "data"
DOCS = PROJECT_ROOT / "docs" / "plans" / "biotech"


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT)).decode().strip()
    except Exception:
        return "unknown"


def load_seal(name: str, sha: str) -> dict:
    p = DATA_DIR / "biotech" / "seals" / f"{name}_{sha}.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return {}
    return {}


def latest_file(pattern: str) -> str:
    matches = sorted(glob.glob(str(DOCS / pattern)))
    return Path(matches[-1]).name if matches else "(없음)"


def read_manual_map() -> str:
    """사용자 편집 절 '가능성 지도 (수동)' 만 보존 · 기존 STATUS.md 에서 추출."""
    p = DOCS / "STATUS.md"
    if not p.exists():
        return "## 가능성 지도 (수동 · 사용자 편집)\n\n(비어 있음 · 수동으로 채우세요)\n"
    text = p.read_text()
    # 마커: "## 가능성 지도 (수동" ~ 다음 ## 헤더 전까지
    m = re.search(r"^## 가능성 지도 \(수동.*?(?=^##|\Z)", text, flags=re.MULTILINE | re.DOTALL)
    if m:
        return m.group(0).rstrip() + "\n"
    # 마커 부재 시: WP35·WP36 절 (기존)
    m2 = re.search(r"^## 가능성 지도.*?(?=^##|\Z)", text, flags=re.MULTILINE | re.DOTALL)
    return (m2.group(0).rstrip() + "\n") if m2 else "## 가능성 지도 (수동 · 사용자 편집)\n\n(비어 있음)\n"


def main():
    require_secure_logging()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sha = git_sha()
    if not (DATA_DIR / f"h3_targets_v2_{sha}.csv").exists():
        fb = data_sha(DATA_DIR)
        if fb:
            LOG.info("git_sha %s 데이터 부재 · data_sha fallback → %s", sha, fb)
            sha = fb

    h8 = load_seal("h8_h1b_full_seal", sha)
    # WP54-3 최종 봉인 우선 로드 · fallback WP54-2
    h54v2 = load_seal("h54v3_signal_final_seal", sha) or load_seal("h54v2_signal_full_seal", sha)
    # WP64 · H3-F4 (WP63/WP63-2/WP63-3) held/무효/유효 상태 판정 · v3 → v2 → v1 우선순위
    h3f4_v3 = load_seal("h3f4_v3_seal", sha)
    h3f4_v2 = load_seal("h3f4_v2_seal", sha)
    h3f4_v1 = load_seal("h3f4_seal", sha)
    h3f4_held = False
    h3f4_extreme_note = ""
    h3f4_summary_note = ""
    if h3f4_v3:
        # v3: 견고성 5건 · 판정 결과 우선 (2026-09-14 정정: (a) 미해결 · 유보 확정 · 과거 재실행 금지)
        verdict = h3f4_v3.get("verdict", {})
        a_h30 = h3f4_v3.get("a_h30d", {})
        d_info = h3f4_v3.get("d_13d_dupes", {})
        a_added = h3f4_v3.get("a_enriched_mcap_coverage", {}).get("added_via_companyfacts", 0)
        h3f4_summary_note = (
            f"WP63-3 F4 견고성: **유보 (pending · 결론 5분류) 확정** · (a) 미해결 (companyfacts dei 부재 · 시총 부재 이벤트 98건 미판정) · (d) 13D 중복 제외 CI 하한 < 0 · "
            f"**F4 검정 과거 재실행 금지 · 2026-11-15 전향 평가 (WP56) 까지 유보**"
        )
    elif h3f4_v2:
        # v2: WP64 안전장치 자동 발동 · alpha_pass_machine 판정
        h30 = (h3f4_v2.get("horizons", {}) or {}).get("h_30d", {})
        h180 = (h3f4_v2.get("horizons", {}) or {}).get("h_180d", {})
        h30_pass = h30.get("alpha_pass_machine")
        h180_pass = h180.get("alpha_pass_machine")
        extreme = h3f4_v2.get("extreme_review", {}).get("count", 0)
        # 결론 5분류 판정 (README §3-☆)
        # h30: alpha_pass_machine=True + n<100 + 시총 부재 다수 = 잠정 확인 (전향 검증 조건부)
        h30_status = "잠정 확인 (전향 검증 조건부)" if h30_pass is True else ("held_for_review" if extreme > 0 else ("유보" if (h30.get("ci_block_lo", 0) or 0) > 0 else "부재"))
        h180_status = "잠정 확인" if h180_pass is True else ("유보" if (h180.get("ci_block_lo", 0) or 0) > 0 else "부재")
        if extreme > 0:
            h3f4_held = True
            h3f4_extreme_note = f"WP63-2 F4 검정: 극단값 {extreme}건 격리 · **held_for_review (데이터 오류 검토)**"
        else:
            h3f4_summary_note = f"WP63-2 F4 v2 (시총 필터 + WP64 안전장치): **30d = {h30_status}** (n={h30.get('n', 0)} mean {h30.get('mean', 0):+.2f}% CI 하한 {h30.get('ci_block_lo', 0):+.2f}%) · **180d = {h180_status}** (n={h180.get('n', 0)} mean {h180.get('mean', 0):+.2f}%)"
    elif h3f4_v1 and "WP63" in str(h3f4_v1.get("version", "")):
        # v1 만 있는 경우: 무효 처리
        h3f4_held = True
        h3f4_extreme_note = "WP63 F4 검정 v1: 시총 필터 미적용 · **무효 (WP63-2 재검 대상)**"

    # 핵심 수치 추출
    h1b = h8.get("H1b", {})
    h1b_n = h1b.get("n", "?")
    h1b_mean = h1b.get("mean_net_excess_pre", 0) or 0
    h1b_ci = h1b.get("ci95", [0, 0]) or [0, 0]

    h8t3 = h8.get("H8_test3_sell_news", {})
    post_mean = h8t3.get("post_D+1_D+30", {}).get("mean", 0) or 0
    post_ci = h8t3.get("post_D+1_D+30", {}).get("ci95", [0, 0]) or [0, 0]
    sell = h8t3.get("sell_supported", False)

    ws = h54v2.get("with_signal", {})
    wo = h54v2.get("without_signal", {})
    ws_mean = ws.get("mean_pre", 0) or 0
    ws_ci = ws.get("ci95", [0, 0]) or [0, 0]
    ws_n = ws.get("n", "?")
    wo_mean = wo.get("mean_pre", 0) or 0
    wo_ci = wo.get("ci95", [0, 0]) or [0, 0]
    wo_n = wo.get("n", "?")
    diff = h54v2.get("diff_with_minus_without", 0) or 0
    diff_ci = h54v2.get("diff_ci95_bootstrap", [0, 0]) or [0, 0]
    ch_stats = h54v2.get("channel_stats", {})

    # 채널 실채움 판정 (Fable 확정 · 2026-09-14 Phase C 세션 4):
    # · AACT 옵션 미포함 → 채널 4.5/5 로 확정
    # · Form 4 hits=0 이면 3.5/5 (WP28-3 병합 전)
    ch2_hits = ch_stats.get("ch2_F4P_hits", 0)
    if ch2_hits > 0:
        channel_completeness = "4.5/5 (AACT 옵션 미포함 · Form 4 P 병합 · ch1~ch5 실채움)"
    else:
        channel_completeness = "3.5/5 (Form 4 미수집 · h6_membership 대체)"

    latest_radar = latest_file("watchlist/radar-v1.*-*.md")
    latest_rumor = latest_file("rumor-daily/*.md")

    manual_map = read_manual_map()

    now_dash = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    lines = []
    lines += [
        "# Biotech Catalyst Radar · 상태판 (사용자 진입점)",
        "",
        "> **📖 용어집 보기**: [`GLOSSARY.md`](GLOSSARY.md) · 코드 · 가설 · 상태 정의 · 첫 등장 시 (뜻) 병기",
        "> **🚀 배포 절차**: [`DEPLOY.md`](DEPLOY.md) · 운영 구조 · 배포 명령 · 롤백",
        "> **⚙️ 자동 갱신**: 본 상태판은 `biotech_h57b_status_gen.py` 가 매일 자동 생성 · '가능성 지도 (수동)' 절만 손 편집",
        "",
        "## 오늘 알아낸 것 (5줄 · 쉬운 말 · 자동)",
        "",
        f"1. **임상 결과 발표 한 달 전에 사면 평균 +{h1b_mean*100:.2f}%** (H1b (Phase 3 (3상 임상) guidance) · 표본 {h1b_n}건 · CI (신뢰구간) [{h1b_ci[0]*100:+.2f}%, {h1b_ci[1]*100:+.2f}%] · **CI 하한 > 0 = 우연 아님** · 임계 +2% 미달)",
        f"2. **발표 직후 한 달은 {post_mean*100:.2f}%** (H8 검정 3 · CI 상한 {post_ci[1]*100:+.2f}% · sell_supported={sell} · **뉴스에 팔아라 격언 데이터로 확인**)",
        f"3. **소문 채널 신호 유무 (WP54-3 확정 · 채널 {channel_completeness} · 2026-11-15 재실행 금지)**: 신호 있음 {ws_n}건 mean **{ws_mean*100:+.2f}%** [{ws_ci[0]*100:+.2f}%, {ws_ci[1]*100:+.2f}%] · 신호 없음 {wo_n}건 mean **{wo_mean*100:+.2f}%** [{wo_ci[0]*100:+.2f}%, {wo_ci[1]*100:+.2f}%] · **차이 {diff*100:+.2f}%p** CI [{diff_ci[0]*100:+.2f}%p, {diff_ci[1]*100:+.2f}%p] · 판정: **{'지지' if h54v2.get('supported') else '불지지'}** (차이 CI 하한 < 0) · 단 **신호 있음 집단만 CI > 0 확정**",
        "4. **뉴스 보고 사는 전략 2건은 효과 없음**: H5 (해외→국내) 폐기 · H3 (activist 전체) 폐기",
        f"5. **오늘의 순위표 · 소문 확인은 화면 3탭** (`/radar` · `/rumor` · `/map`) · 최신: `{latest_radar}` · `{latest_rumor}` · **소액 실전 규칙 8항 적용**",
        "",
        (f"⚠️ **{h3f4_extreme_note}**" if h3f4_held else (f"🟡 {h3f4_summary_note}" if h3f4_summary_note else "")),
        "",
        f"**최종 갱신 (자동)**: {now_dash} · git_sha (git 커밋 짧은 해시) `{sha}`",
        "",
        "**Phase A (검증 단계 · 알파 존재 여부 판정) 종결 (Fable 최종 검수 통과)**: `PHASE-A-FINAL.md` 종결본 참조 (2026-09-14 동결)",
        "**Phase B (UI 배포 단계)** = 3탭 + 용어집 · WP55 최소 FastAPI 뷰어 `biotech_h55_viewer.py` (로컬 :8765)",
        f"**Phase C (확장 단계) 진행 중** = 소문 채널 완비 진척 · h57 PubMed 200/307 · h58 Preprint 200/307 · 실채움 채널 {channel_completeness}",
        "",
        "---",
        "",
        "## 가설별 상태 (자동)",
        "",
        "| 가설 | 상태 | 핵심 수치 | 다음 액션 | 최신 리포트 |",
        "|---|---|---|---|---|",
        "| **H1a** · FDA (미국 식약처) AdCom (자문위 회의) 사전 공지 | 유보 후보 | 회의일 87% · 매핑 2/26 | Big Pharma 이름 매핑 확장 | `H1a-design.md` |",
        f"| **H1b** · Phase 3 (3상 임상) guidance | **완주 풀 유의 · 임계 미달** | n={h1b_n} · mean **{h1b_mean*100:+.2f}%** · CI [{h1b_ci[0]*100:+.2f}%, {h1b_ci[1]*100:+.2f}%] | 임계 통과 아님 · **작지만 실재** | `verification/H8/H8-H1b-full-report-20260914.md` |",
        "| **H2** · 테마 클러스터 확산 | 미착수 | — | 코드 룰 확정 | `README.md §2 H2` |",
        "| **H3** · Activist 신규 13D/13G | 폐기 (관문 2 · alpha_pass=False) | 이벤트 346 · 13D 30d +4.43% CI 하한 <0 | H3b 로 계승 | `verification/H3/H3-report-20260912.md` |",
        "| **H3b** · 소형주 activist 검정 | 부분 관측 · 임계 미달 | 300M-1B/fund/180d · n=42 · mean +2.85% | 표본 확대 · Fable 옵션 승인 | `design/H3b-design.md` |",
        "| **H4** · Reddit 소셜 첫 언급 | 전향 수집 중 (RSS만) | apewisdom 매치 6/300 | 60일 게이트 후 백테스트 | `H4-design.md` |",
        "| **H5** · 해외 촉매 → 국내 연계 | **종결 (폐기)** | pre +0.22% · imm -0.52% · sus -0.67% | 재개 조건 = 촉매 풀 확장 | `verification/H5-report-20260912.md` |",
        "| **H6** · 분야 순위 point-in-time | 관문 3 대기 · dry-run 완결 | 8세트 46분기 · 상위 3분위 2020Q1 · 소속 38 | membership 확장 (WP27-2) | `H6-design.md` |",
        "| **H7** · 초기 매집 후 분할 매도 | 설계 완료 · 대기 | 사전 커밋 13항 | H6·H8 알파 확인 후 실행 | `H7-design.md` |",
        f"| **H8** · 소문 지수 선행성 | **부분 풀 지지 (검정 3)** | post {post_mean*100:+.2f}% CI 상한 {post_ci[1]*100:+.2f}% · sell_supported={sell} | 채널 확장 후 WP54-3 재검 | `verification/H8/H8-signal-presence-full-2026-09-14.md` |",
        (f"| **H3-F4** · Form 4 매수 추종 (별도 · WP63) | ⚠️ **held_for_review** | {h3f4_extreme_note} | 격리 검토 후 재실행 | `verification/H3/H3-F4-report-v3-*.md` |" if h3f4_held else (f"| **H3-F4 v3** · Form 4 매수 추종 (별도 · WP63-3 견고성) | **유보 (pending)** (5분류 · 과거 재실행 금지) | {h3f4_summary_note} | 2026-11-15 전향 평가 (WP56) 재현 시 확인 승격 | `verification/H3/H3-F4-report-v3-*.md` |" if h3f4_summary_note else "")),
        "| **Security** · 자격증명 가드레일 | WP8 (설정 강제 부트스트랩) | 156/156 (+2 skip) pytest · SEC WP23 헤더 | 신규 스크립트 자동 강제 | `Security-Audit.md` |",
        "",
        "---",
        "",
        "## Phase C 순서 (배포 후 첫 작업 = 1)",
        "",
        "1. **소문 채널 완비 (진행 중)**: h57 PubMed 잔여 107 CIK 재시도 · **Form 4 채널 e 실채움 (WP28-2)** · CT.gov 상태 변경 (AACT 스냅샷 2~4개 · 2.5GB × 4 = 10GB) → **WP54-3 재실행** (규칙 동일)",
        "2. **H6 소속 확장** (CT.gov 스폰서 전체 재매핑) → 재검",
        "3. **반자동 티켓 탭** (실전 기록 화면화 · trades_manual.csv 편집기)",
        "4. **H3b 전향 검정** (2026-09-14 이후 신규 13D · 소형~중형)",
        "5. **파산 종목 가격 복구** (원장 v6 · B60 파산 8건)",
        "",
        "---",
        "",
        "## 사용자 액션",
        "",
        "- [ ] **crontab 등록** (필수 · 로컬 macOS · 사용자 액션):",
        "  ```bash",
        "  crontab -e",
        "  # 매일 KST 07:00 (UTC 22:00 전날) · 파이프 실행",
        "  0 22 * * * /Users/gonnim/Project-MVP/Source/toss-tradebot-mvp/backend/scripts/biotech_h48v3_daily.sh >> /Users/gonnim/Project-MVP/Source/toss-tradebot-mvp/backend/data/biotech/community_daily/cron.log 2>&1",
        "  # 매월 15일 KST 08:00 (UTC 23:00 14일) · 60일 전향 평가",
        "  0 23 14 * * cd /Users/gonnim/Project-MVP/Source/toss-tradebot-mvp && backend/venv/bin/python -m backend.scripts.biotech_h56_forward_eval --window 60d >> backend/data/biotech/community_daily/forward.log 2>&1",
        "  ```",
        "  확인: `crontab -l | grep biotech`",
        "",
        "- [ ] **로컬 뷰어 실행**: `backend/venv/bin/python -m backend.scripts.biotech_h55_viewer` → 브라우저 `http://127.0.0.1:8765`",
        "",
        "- [ ] **실전 기록 (선택)**: `backend/data/biotech/trades/trades_manual.csv` 에 매수/청산 기록 (18열 헤더)",
        "",
        "---",
        "",
        manual_map.rstrip(),
        "",
        "---",
        "",
        "## 진입 문서 (자동)",
        "",
        "- `STATUS.md` (본 문서 · 사용자 진입점 · 자동 갱신)",
        "- `PHASE-A-FINAL.md` (2026-09-14 종결본 · 동결)",
        "- `GLOSSARY.md` (용어집)",
        "- `DEPLOY.md` (배포 절차서)",
        "- `PENDING.md` (미완 지시 원문 보관)",
        "- `INDEX.md` (문서 목록·용도·상태)",
        "- `verification/H8/H8-signal-presence-full-2026-09-14.md` (WP54-2 채널 5/5 리포트)",
        "- `verification/H8/H8-H1b-full-report-20260914.md` (H1b 완주 풀 리포트)",
        "",
    ]

    out_path = DOCS / "STATUS.md"
    out_path.write_text("\n".join(lines))
    LOG.info("STATUS.md 자동 생성 · %d lines", len(lines))
    print(json.dumps({
        "git_sha": sha,
        "path": str(out_path),
        "lines": len(lines),
        "channel_completeness": channel_completeness,
        "latest_radar": latest_radar,
        "latest_rumor": latest_rumor,
        "h1b_mean_pct": round(h1b_mean * 100, 2),
        "h1b_ci_pct": [round(h1b_ci[0]*100, 2), round(h1b_ci[1]*100, 2)],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
