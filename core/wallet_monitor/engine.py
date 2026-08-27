"""
錢包監測引擎——抓取 TonAPI events → 比對用戶警示規則 → 產生 AlertEvent

分層（對應 design doc）：
    fetch_events()        → TonAPI /v2/accounts/{addr}/events（實測驗證可用）
         │
         ▼
    match_rules()         → 比對用戶設定的警示規則（轉入/轉出/詐騙/大額）
         │
         ▼
    AlertEvent            → 統一事件結構，送給 AlertDispatcher（channels.py）

設計取捨：
    - 純函式、無 side effect（發送在 channels.py）——可獨立測試。
    - graceful：任何 API 失敗不中斷，回空事件列表。
    - 上次已處理的 event 用 event_id 去重（Redis 快取 last_processed_event_id）。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from core.config import WALLET_MONITOR_INTERVAL_MINUTES
from core.shared_cache import get_json, set_json

logger = logging.getLogger(__name__)

_TONAPI_EVENTS_URL = "https://tonapi.io/v2/accounts/{address}/events"
# 單次抓取上限（筆）。
_MAX_EVENTS_PER_FETCH = 20
# 去重快取 key + TTL（事件抓過就不重複警示，TTL = 輪詢間隔 × 3 保險）。
_LAST_EVENT_KEY = "wallet_monitor:last_event:{address}"
_LAST_EVENT_TTL = max(300, WALLET_MONITOR_INTERVAL_MINUTES * 60 * 3)


@dataclass
class AlertEvent:
    """統一警示事件（送給 AlertDispatcher 的標準格式）。"""

    wallet_address: str
    event_id: str
    event_type: str  # "incoming" / "outgoing" / "scam_contact" / "large_out"
    amount_ton: float
    counterparty: str  # 對端地址
    is_scam: bool
    timestamp: int
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wallet_address": self.wallet_address,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "amount_ton": self.amount_ton,
            "counterparty": self.counterparty,
            "is_scam": self.is_scam,
            "timestamp": self.timestamp,
        }


async def fetch_events(address: str) -> List[Dict[str, Any]]:
    """抓取錢包最近的 events（TonAPI）。

    Returns:
        list of raw event dicts（含 actions、timestamp、is_scam）。失敗回空。
    """
    addr = (address or "").strip()
    if not (addr.startswith("EQ") or addr.startswith("UQ") or addr.startswith("0Q")):
        return []

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                _TONAPI_EVENTS_URL.format(address=addr),
                params={"limit": _MAX_EVENTS_PER_FETCH},
            )
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except httpx.HTTPError as exc:
        logger.warning("[wallet_monitor] fetch events failed %s: %s", addr, exc)
        return []

    if resp.status_code != 200:
        logger.warning("[wallet_monitor] events %s -> HTTP %s", addr, resp.status_code)
        return []

    body = resp.json()
    return body.get("events", []) or []


def _is_already_processed(address: str, event_id: str) -> bool:
    """檢查 event 是否已處理過（用上次 event_id 去重——events 依時間排序，
    上次處理到的最新 event_id 之前的都算已處理）。"""
    last_id = get_json(_LAST_EVENT_KEY.format(address=address))
    if not last_id:
        return False
    # 若 event_id 存在於「已處理的集合」——v1 用「只處理比 last_id 新的事件」
    # 簡化：因為 events 是新的在前，抓到的事件中「碰到 last_id 就停」。
    return event_id == last_id


def _mark_processed(address: str, event_id: str) -> None:
    set_json(_LAST_EVENT_KEY.format(address=address), event_id, _LAST_EVENT_TTL)


def _extract_transfer(action: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """從 action 取出轉帳資訊(支援 TonTransfer + JettonTransfer)。

    回傳 dict 統一格式:
      type: "ton" | "jetton"
      amount: 原始整數(nanoTON 或 jetton 最小單位)
      sender / recipient: 地址
      comment: 留言(僅 TonTransfer 有)
      symbol / name / decimals: 僅 jetton
    """
    atype = action.get("type", "")

    if atype == "TonTransfer":
        tt = action.get("TonTransfer", {})
        return {
            "type": "ton",
            "amount": tt.get("amount", 0),  # nanoTON
            "sender": (tt.get("sender", {}) or {}).get("address", ""),
            "recipient": (tt.get("recipient", {}) or {}).get("address", ""),
            "comment": tt.get("comment", ""),
        }

    if atype == "JettonTransfer":
        jt = action.get("JettonTransfer", {})
        jetton = jt.get("jetton", {}) or {}
        return {
            "type": "jetton",
            "amount": jt.get("amount", 0),  # jetton 最小單位
            "sender": (jt.get("sender", {}) or {}).get("address", ""),
            "recipient": (jt.get("recipient", {}) or {}).get("address", ""),
            "comment": jt.get("comment", ""),
            "symbol": jetton.get("symbol", ""),
            "name": jetton.get("name", ""),
            "decimals": jetton.get("decimals", 9),
        }

    return None


def match_rules(
    address: str,
    events: List[Dict[str, Any]],
    settings: Dict[str, Any],
) -> List[AlertEvent]:
    """比對 events 與用戶警示規則，產生 AlertEvent 列表。

    Args:
        address: 被監測的錢包地址。
        events: fetch_events 的 raw events。
        settings: 用戶的警示設定（JSONB 結構，見 migration c018）。

    Returns:
        符合規則的 AlertEvent 列表（新的在前）。已處理的去重。
    """
    alerts_cfg = (settings or {}).get("alerts", {})
    incoming_cfg = alerts_cfg.get("incoming", {})
    outgoing_cfg = alerts_cfg.get("outgoing", {})
    scam_cfg = alerts_cfg.get("scam", {})
    large_out_cfg = alerts_cfg.get("large_out", {})

    matches: List[AlertEvent] = []
    processed_any = False

    for ev in events:
        event_id = ev.get("event_id", "")
        if not event_id:
            continue
        # 去重：碰到已處理的最新 event_id 就停止（events 新的在前）
        if _is_already_processed(address, event_id):
            break
        processed_any = True

        ts = ev.get("timestamp", 0)
        is_scam = bool(ev.get("is_scam"))

        for action in ev.get("actions", []) or []:
            transfer = _extract_transfer(action)
            if not transfer:
                continue
            sender = transfer["sender"]
            recipient = transfer["recipient"]

            # 詐騙往來（任何一方是 scam 標記）— jetton 也算
            if is_scam and scam_cfg.get("enabled", True):
                matches.append(AlertEvent(
                    wallet_address=address, event_id=event_id,
                    event_type="scam_contact", amount_ton=0.0,
                    counterparty=sender if recipient == address else recipient,
                    is_scam=True, timestamp=ts,
                ))

            # TON 金額規則只適用 TonTransfer(jetton 的 amount 不是 nanoTON)
            if transfer.get("type") != "ton":
                continue

            amount_nano = int(transfer["amount"] or 0)
            amount_ton = amount_nano / 1e9

            if amount_ton <= 0:
                continue

            # 轉入（別人 → 被監測錢包）
            if recipient == address and incoming_cfg.get("enabled"):
                if amount_ton >= float(incoming_cfg.get("min_amount_ton", 0)):
                    matches.append(AlertEvent(
                        wallet_address=address, event_id=event_id,
                        event_type="incoming", amount_ton=amount_ton,
                        counterparty=sender, is_scam=is_scam, timestamp=ts,
                    ))

            # 轉出（被監測錢包 → 別人）
            if sender == address and outgoing_cfg.get("enabled"):
                if amount_ton >= float(outgoing_cfg.get("min_amount_ton", 0)):
                    matches.append(AlertEvent(
                        wallet_address=address, event_id=event_id,
                        event_type="outgoing", amount_ton=amount_ton,
                        counterparty=recipient, is_scam=is_scam, timestamp=ts,
                    ))

            # 大額轉出（閾值）
            if sender == address and large_out_cfg.get("enabled"):
                if amount_ton >= float(large_out_cfg.get("threshold_ton", 500)):
                    matches.append(AlertEvent(
                        wallet_address=address, event_id=event_id,
                        event_type="large_out", amount_ton=amount_ton,
                        counterparty=recipient, is_scam=is_scam, timestamp=ts,
                    ))


    # 更新去重標記（處理到的最新 event_id = 第一筆的 event_id）
    if processed_any and events:
        latest_id = events[0].get("event_id", "")
        if latest_id:
            _mark_processed(address, latest_id)

    return matches


__all__ = ["AlertEvent", "fetch_events", "match_rules"]
