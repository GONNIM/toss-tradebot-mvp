// WP79 · cardText() 확인 스크립트 (backend/tests/test_biotech_wp74_display.py 가 tsx 로 실행)
import assert from "node:assert/strict";
import { cardText } from "./biotech-display";

const beauty = cardText({ category: "미용", interventions: [{ name: "X-1", type: "DRUG", type_ko: "약물" }] }, "PHASE2", "2026-11-30", 62);
assert.ok(beauty.main?.startsWith("미용 · X-1 (약물) · 2상(효과 탐색)"), beauty.main ?? "null");

const other = cardText({ category: "기타", enrollment: "24" }, "PHASE1", "2026-10-31", 32);
assert.ok(other.main?.startsWith("기타 · 1상(안전성 확인) · 참가자 24명"), other.main ?? "null");

const raw = cardText({ category: "기타 (Healthy Volunteers)" }, "PHASE1", "2026-10-31", 32);
assert.ok(raw.main?.startsWith("기타 (Healthy Volunteers) · 1상"), raw.main ?? "null");
// WP80 · 신설 분류 3개 · 설명 문구 포함
const hv = cardText({ category: "건강인·약동학" }, "PHASE1", "2026-10-31", 32);
assert.ok(hv.main?.startsWith("건강인·약동학(건강한 사람 대상 안전성·약동학 시험) · 1상"), hv.main ?? "null");
const pain = cardText({ category: "통증" }, "PHASE2", "2026-10-31", 32);
assert.ok(pain.main?.startsWith("통증(통증 치료 시험) · 2상"), pain.main ?? "null");
const ent = cardText({ category: "청각·이비인후" }, "PHASE3", "2026-10-31", 32);
assert.ok(ent.main?.startsWith("청각·이비인후(청각·귀 질환 시험) · 3상"), ent.main ?? "null");
// WP81 · 자동 분류는 "분류(자동) · …" 로 시작 (설명 문구 대신 자동 표시)
const auto = cardText({ category: "신경·정신", category_auto: true }, "PHASE2", "2026-10-31", 32);
assert.ok(auto.main?.startsWith("신경·정신(자동) · 2상"), auto.main ?? "null");
const autoNew = cardText({ category: "통증", category_auto: true }, "PHASE2", "2026-10-31", 32);
assert.ok(autoNew.main?.startsWith("통증(자동) · 2상"), autoNew.main ?? "null");
console.log("ok");
