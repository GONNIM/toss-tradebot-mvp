#!/usr/bin/env python3
"""Fable 검수용 번들 zip 생성기 (2026-09-28 사용자 규칙 · 이후 모든 Fable 확인 요청에 적용).

사용:
    python3 scripts/fable_bundle.py <주제> <파일 또는 폴더> [...] [--question "검수 질문"]...

동작:
- 저장소 루트 기준 경로 그대로 zip 안에 담는다 (Fable 이 보고서의 전체 경로 표기와 대조 가능)
- 맨 앞에 MANIFEST.md (주제 · 생성 시각 KST · git 커밋 · 파일별 크기·SHA-256 · 검수 질문) 를 넣는다
- 자격증명 시그니처 (글로벌 규칙 §1.2) 가 보이면 zip 을 만들지 않고 중단한다
- __MACOSX · .DS_Store · 숨김 파일 · 스크린샷 원본 (png·webp) 은 넣지 않는다 (--with-images 로만 포함)
- 출력: docs/plans/biotech/fable-bundles/<YYYYMMDD>_<주제>.zip (git 제외 폴더)
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "plans" / "biotech" / "fable-bundles"
KST = timezone(timedelta(hours=9))
IMAGE_EXT = {".png", ".webp", ".jpg", ".jpeg", ".gif"}

# 글로벌 CLAUDE.md §1.2 시그니처 (요약 · 값 출력 없이 파일·줄만 보고)
SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"sk-(ant-)?[A-Za-z0-9_-]{20,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY-----"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}"),
    re.compile(r"(?i)(client_secret|db_password|aws_secret_access_key)['\"]?\s*[:=]\s*\S+"),
    re.compile(r"(?i)(secret|token|password|api[_-]?key)\w*['\"]?\s*[:=]\s*['\"]?[A-Za-z0-9+/=_-]{40,}"),
]


def _collect(paths: list[str], with_images: bool) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        path = (ROOT / p).resolve()
        if not path.exists():
            sys.exit(f"없는 경로: {p}")
        items = [path] if path.is_file() else sorted(x for x in path.rglob("*") if x.is_file())
        for f in items:
            rel = f.relative_to(ROOT)
            if any(part.startswith(".") or part == "__MACOSX" for part in rel.parts):
                continue
            if f.suffix.lower() in IMAGE_EXT and not with_images:
                continue
            if f.suffix.lower() == ".zip":
                continue
            out.append(f)
    return sorted(set(out))


def _scan(files: list[Path]) -> list[str]:
    hits = []
    for f in files:
        try:
            text = f.read_text(errors="ignore")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if any(p.search(line) for p in SECRET_PATTERNS):
                hits.append(f"{f.relative_to(ROOT)}:{i}")
    return hits


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("topic", help="주제 (파일명에 쓰임 · 예: H6-gate2)")
    ap.add_argument("paths", nargs="+", help="저장소 루트 기준 파일·폴더")
    ap.add_argument("--question", action="append", default=[], help="Fable 에게 묻는 검수 질문 (여러 번 가능)")
    ap.add_argument("--with-images", action="store_true", help="스크린샷 이미지도 포함")
    args = ap.parse_args()

    files = _collect(args.paths, args.with_images)
    if not files:
        sys.exit("담을 파일이 없습니다")
    hits = _scan(files)
    if hits:
        sys.exit("🚨 자격증명 의심 패턴 · 번들 중단 · " + ", ".join(hits))

    sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT).decode().strip()
    now = datetime.now(KST)
    safe_topic = re.sub(r"[^A-Za-z0-9._-]+", "-", args.topic).strip("-")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{now:%Y%m%d}_{safe_topic}.zip"

    lines = [
        f"# Fable 검수 번들 · {args.topic}",
        "",
        f"- 생성: {now:%Y-%m-%d %H:%M} KST",
        f"- 저장소 커밋: `{sha}`",
        f"- 파일 {len(files)}개 · 경로는 저장소 루트 기준",
        "- 자격증명 시그니처 검사: 통과",
        "",
        "## 검수 질문",
        "",
    ]
    lines += [f"{i}. {q}" for i, q in enumerate(args.question, 1)] or ["(질문 없음 · 보고서 본문 참조)"]
    lines += ["", "## 파일 목록", "", "| 경로 | 크기 (B) | SHA-256 앞 12자 |", "|---|---|---|"]
    for f in files:
        data = f.read_bytes()
        lines.append(f"| `{f.relative_to(ROOT)}` | {len(data):,} | `{hashlib.sha256(data).hexdigest()[:12]}` |")

    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("MANIFEST.md", "\n".join(lines) + "\n")
        for f in files:
            zf.write(f, arcname=str(f.relative_to(ROOT)))
    print(f"{out.relative_to(ROOT)} · 파일 {len(files)}개 · {out.stat().st_size:,} B")


if __name__ == "__main__":
    main()
