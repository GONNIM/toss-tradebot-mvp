// 1022-09 · 알림 설정 화면 표시 함수 확인 (backend/tests/test_notifications_display.py 가 tsx 로 실행)
import assert from "node:assert/strict";
import { groupRows, recommendedText, modeText, intervalText, whenText, isRecommended, canEdit } from "./notifications-display";
import type { NotificationSettingRow } from "./api";

const base: NotificationSettingRow = {
  category: "vip", label: "VIP 감시", group: "⑤ VIP", page: "/vip", locked: false, configurable: true,
  recommended: { resend_minutes: 10080 }, reason: "같은 종목은 7일에 한 번", enabled: true, mode: "immediate",
  resend_minutes: 0, min_level: "info", editable: ["enabled", "mode", "resend_minutes", "min_level"], last_sent_at: null, last_failed_at: null, last_error: null, skipped_today: 0,
};

// 묶음 순서 유지 · 같은 묶음끼리
const g = groupRows([base, { ...base, category: "a", group: "① Serenity" }, { ...base, category: "b" }]);
assert.deepEqual(g.map((x) => x.group), ["⑤ VIP", "① Serenity"]);
assert.deepEqual(g[0].rows.map((r) => r.category), ["vip", "b"]);

// 권고값 문장 — 내부 코드 없이 한국어
assert.equal(recommendedText({ resend_minutes: 10080 }), "같은 알림은 7일에 한 번");
assert.equal(recommendedText({ enabled: false }), "끄기");
assert.equal(recommendedText({ mode: "digest" }), "하루 요약 (18:00)");
assert.equal(recommendedText({ min_level: "warning" }), "경고 이상만");
assert.equal(recommendedText({}), "지금 그대로");

assert.equal(modeText("immediate"), "바로 받기");
assert.equal(modeText("digest"), "하루 요약 (18:00)");
assert.equal(intervalText(0), "제한 없음");
assert.equal(intervalText(60), "1시간");
assert.equal(intervalText(1440), "1일");
assert.equal(intervalText(90), "90분");

// 시각 — UTC 문자열을 한국 시각으로
assert.equal(whenText(null), "없음");
assert.equal(whenText("2026-10-23T03:05:00Z"), "10/23 12:05");

// 권고값과 같은지
assert.equal(isRecommended(base), false);
assert.equal(isRecommended({ ...base, resend_minutes: 10080 }), true);
// 권고에 끄기가 없는데 꺼 두었으면 권고와 다름
assert.equal(isRecommended({ ...base, resend_minutes: 10080, enabled: false }), false);
// 바꿀 수 있는 칸 (서버 editable 기준)
assert.equal(canEdit({ ...base, editable: ["mode"] }, "mode"), true);
assert.equal(canEdit({ ...base, editable: ["mode"] }, "min_level"), false);
assert.equal(canEdit({ ...base, editable: [] }, "enabled"), false);
console.log("notifications-display ok");
