"""EVM 鏈介面卡（路線 C）——服務級 Etherscan V2 多鏈。

docs/plans/2026-08-11-wallet-monitor-multichain-design.md

與 etherscan.py 的 BYOK 工具不同——錢包監測是背景 cron 輪詢，沒有使用者
的 key 可用。本 adapter 用服務級 ETHERSCAN_SERVICE_API_KEY。

Phase 1 支援 Ethereum mainnet + BSC + Polygon（最高流量三條）。
其他鏈只要 chain_id 對就可用（_SUPPORTED_CHAINS 可擴充）。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from .base import ChainBalance, WalletChainAdapter

logger = logging.getLogger(__name__)

_ETHERSCAN_ENDPOINT = "https://api.etherscan.io/v2/api"
_WEI_PER_ETH = 10**18

# chain_id → (chain_label, native_symbol, decimals)
# ⚠️ 實測免費 Etherscan key 只支援部分鏈（Ethereum/Polygon/Arbitrum）。
# BSC/Optimism/Base/Avalanche 需付費 plan。僅列免費可用的鏈，
# 避免使用者設了 BYOK key 卻查不到資料。付費 plan 可自行擴充此表。
_SUPPORTED_CHAINS = {
    1: ("ethereum", "ETH", 18),
    137: ("polygon", "MATIC", 18),
    42161: ("arbitrum", "ETH", 18),
}

# chain_name → chain_id（解析用）
_CHAIN_NAME_TO_ID = {
    "eth": 1, "ethereum": 1,
    "polygon": 137, "matic": 137,
    "arbitrum": 42161, "arb": 42161,
}


def _service_etherscan_key() -> Optional[str]:
    """取得服務級 Etherscan key（fallback，模式 B 主要用使用者 BYOK key）。"""
    return os.getenv("ETHERSCAN_SERVICE_API_KEY")


def resolve_evm_chain_id(name: str) -> Optional[int]:
    """鏈名 → chain_id；未知回 None。"""
    return _CHAIN_NAME_TO_ID.get((name or "").strip().lower())


class EvmAdapter(WalletChainAdapter):
    """EVM 鏈介面卡（Etherscan V2，模式 B：使用者 BYOK key 優先，服務 key fallback）。"""

    def __init__(self, chain_id: int):
        if chain_id not in _SUPPORTED_CHAINS:
            raise ValueError(f"Unsupported EVM chain_id {chain_id}")
        self._chain_id = chain_id
        self._label, self._symbol, self._decimals = _SUPPORTED_CHAINS[chain_id]

    @property
    def chain(self) -> str:
        return self._label

    @property
    def native_symbol(self) -> str:
        return self._symbol

    def is_valid_address(self, address: str) -> bool:
        addr = (address or "").strip()
        return addr.startswith("0x") and len(addr) == 42

    def _etherscan_get(self, params: dict, api_key: Optional[str] = None) -> Optional[dict]:
        """Etherscan V2 呼叫。模式 B：優先用使用者 BYOK key，fallback 服務 key。

        無任何 key → None（graceful，該錢包跳過）。
        """
        key = api_key or _service_etherscan_key()
        if not key:
            logger.debug("[EvmAdapter] no Etherscan key (BYOK or service) — skipping")
            return None
        query = {"chainid": self._chain_id, **params, "apikey": key}
        try:
            resp = httpx.get(_ETHERSCAN_ENDPOINT, params=query, timeout=15.0)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[EvmAdapter] etherscan failed: %s", exc)
            return None

    async def fetch_events(self, address: str, api_key: Optional[str] = None) -> List[Dict[str, Any]]:
        """Etherscan txlist → 統一 event dict（incoming/outgoing）。

        模式 B：api_key 是使用者的 BYOK key（cron 傳入）；None 時 fallback 服務 key。
        """
        if not self.is_valid_address(address):
            return []
        data = self._etherscan_get({
            "module": "account",
            "action": "txlist",
            "address": address,
            "startblock": 0,
            "endblock": 99999999,
            "page": 1,
            "offset": 20,
            "sort": "desc",
        }, api_key=api_key)
        if not data or data.get("status") != "1":
            return []
        events = []
        for tx in (data.get("result") or [])[:20]:
            is_outgoing = tx.get("from", "").lower() == address.lower()
            events.append({
                "event_id": tx.get("hash", ""),
                "event_type": "outgoing" if is_outgoing else "incoming",
                "amount_raw": int(tx.get("value", 0)),
                "counterparty": tx.get("to" if is_outgoing else "from", ""),
                "is_scam": False,  # EVM 無免費 scam 標記；Phase 2 接 GoPlus
                "timestamp": int(tx.get("timeStamp", 0)),
            })
        return events

    def translate_events(
        self, address: str, raw_events: List[Dict[str, Any]], settings: Dict[str, Any]
    ) -> List[Any]:
        """把統一 event dict 翻譯成 AlertEvent（USD 門檻比對）。"""
        from core.wallet_monitor.engine import AlertEvent

        result = []
        incoming_cfg = settings.get("alerts", {}).get("incoming", {})
        outgoing_cfg = settings.get("alerts", {}).get("outgoing", {})
        large_out_cfg = settings.get("alerts", {}).get("large_out", {})

        # 簡化：用 raw amount（wei）的 log10 當近似量級。
        # Phase 2 用真實幣價換算 USD 門檻。
        for ev in raw_events:
            amount_raw = ev.get("amount_raw", 0)
            amount = amount_raw / (10 ** self._decimals) if self._decimals else amount_raw
            etype = ev.get("event_type", "")
            if etype == "incoming" and incoming_cfg.get("enabled"):
                result.append(AlertEvent(
                    wallet_address=address,
                    event_id=ev.get("event_id", ""),
                    event_type="incoming",
                    amount_ton=amount,  # 欄位名歷史遺留；值是原生幣量
                    counterparty=ev.get("counterparty", ""),
                    is_scam=ev.get("is_scam", False),
                    timestamp=ev.get("timestamp", 0),
                ))
            elif etype == "outgoing":
                if large_out_cfg.get("enabled") and amount >= float(large_out_cfg.get("min_amount_ton", 999999)):
                    result.append(AlertEvent(
                        wallet_address=address,
                        event_id=ev.get("event_id", ""),
                        event_type="large_out",
                        amount_ton=amount,
                        counterparty=ev.get("counterparty", ""),
                        is_scam=False,
                        timestamp=ev.get("timestamp", 0),
                    ))
                elif outgoing_cfg.get("enabled"):
                    result.append(AlertEvent(
                        wallet_address=address,
                        event_id=ev.get("event_id", ""),
                        event_type="outgoing",
                        amount_ton=amount,
                        counterparty=ev.get("counterparty", ""),
                        is_scam=False,
                        timestamp=ev.get("timestamp", 0),
                    ))
        return result

    async def fetch_balance(self, address: str, api_key: Optional[str] = None) -> Optional[ChainBalance]:
        if not self.is_valid_address(address):
            return None
        data = self._etherscan_get({
            "module": "account",
            "action": "balance",
            "address": address,
            "tag": "latest",
        }, api_key=api_key)
        if not data or data.get("status") != "1":
            return None
        amount = int(data["result"]) / (10 ** self._decimals)
        return ChainBalance(amount=amount, symbol=self._symbol, chain=self._label)
