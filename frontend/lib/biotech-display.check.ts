// WP79 · cardText() 확인 스크립트 (backend/tests/test_biotech_wp74_display.py 가 tsx 로 실행)
import assert from "node:assert/strict";
import { cardText } from "./biotech-display";

const beauty = cardText({ category: "미용", interventions: [{ name: "X-1", type: "DRUG", type_ko: "약물" }] }, "PHASE2", "2026-11-30", 62);
assert.ok(beauty.main?.startsWith("미용 · X-1 (약물) · 2상(효과 탐색)"), beauty.main ?? "null");

const other = cardText({ category: "기타", enrollment: "24" }, "PHASE1", "2026-10-31", 32);
assert.ok(other.main?.startsWith("기타 · 1상(안전성 확인) · 참가자 24명"), other.main ?? "null");

const raw = cardText({ category: "기타 (Healthy Volunteers)" }, "PHASE1", "2026-10-31", 32);
assert.ok(raw.main?.startsWith("기타 (Healthy Volunteers) · 1상"), raw.main ?? "null");
console.log("ok");
