"""VIP 알림 포맷팅 — 기존 [[TelegramNotifier]] send_info 재활용.

제목: `<아이콘> VIP 감시 · <회사> <사건>` (1023-05 · 사건 이름은 alert_text.VIP_EVENT)
"""
from __future__ import annotations

import logging

from backend.services import alert_text as at
from backend.services.notifier import TelegramNotifier

from .activist_tracker import Filing
from .config import VipConfig
from .position import Event

logger = logging.getLogger(__name__)

async def send_position_event(
    notifier: TelegramNotifier,
    event: Event,
    cfg: VipConfig,
) -> bool:
    icon, name = at.VIP_EVENT.get(event.name, ("📣", at.esc(event.name)))
    fact = f"{cfg.company_name} {name}"
    if event.name in ("STOP_APPROACH", "TRAIL_GIVEBACK"):
        fact += f" ({at.pct(event.pnl)})"
    title = at.title("vip", at.esc(fact), icon)
    lines = [f"산 값 {at.usd(cfg.avg_price)} → 지금 {at.usd(event.current_price)} ({at.pct(event.pnl)})"]
    if cfg.qty > 0:
        pnl_usd = (event.current_price - cfg.avg_price) * cfg.qty
        lines.append(f"{cfg.qty:g}주 · 평가 손익 {at.signed_usd(pnl_usd)}")
    if event.name == "STOP_APPROACH":
        lines.append(f"손절 기준 {at.pct(cfg.stop_pct)} · 지금 {at.pct(event.pnl)}")
    lines.append(at.link("vip"))
    return await notifier.send_info(title, "\n".join(lines), category="vip", dedupe_id=f"{cfg.tag}:{event.name}")


async def send_activist_filing(
    notifier: TelegramNotifier,
    filing: Filing,
    cfg: VipConfig,
) -> bool:
    from backend.discovery.activist.hints import sec_filing_detail_url

    icon, name = at.VIP_EVENT["ACTIVIST_FILING"]
    actor = cfg.activist_name or "행동주의 운용사"
    title = at.title("vip", at.esc(f"{cfg.company_name} {name}"), icon)
    lines = [f"{at.esc(actor)} 의 {at.sec_form_text(filing.form)} · {at.md(filing.filing_date)}"]
    if filing.primary_desc:
        lines.append(f"내용: {at.esc(filing.primary_desc)}")
    url = sec_filing_detail_url(cfg.activist_cik, filing.accession)
    if url:
        lines.append(f"SEC 원문: {url}")
    lines.append(at.link("vip"))
    return await notifier.send_info(title, "\n".join(lines), category="vip", dedupe_id=f"{cfg.tag}:{filing.accession}")
