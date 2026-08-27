"""Omniston BuildSwap spike — 從 quote 到可簽章 message body (v1beta8)。

M3 spike 第二交付物：證明 BuildSwap API 能產出「可被 tonConnectUI.sendTransaction
接受的 swap message body」。延續 M1 quote_poc.py 的精神——READ-ONLY：

  BuildSwap 本身不簽章、不上鏈、不動錢。它只是把 quote_id + 錢包地址送進
  Omniston，換回一組未簽章的 TON message（target/amount/payload）。
  真正簽章是前端 TON Connect 的事（另一道人工確認）。

所以這個 PoC 對資金的風險 = 0。跟 M1 一樣安全地打 production WS。

驗證流程（對應 spike 三件事）：
  1. Quote 訂閱 → 拿 quote_id（複用 M1 已驗證的協議）
  2. BuildSwap unary RPC → 拿 TonTransaction.messages（★ 真實 message body ★）
  3. 驗證 message 格式相容 sendTransaction（hex payload → 需 hexToBase64）

Wire format 差異（為何不能直接抄 M1）：
  - Quote 是 subscribe stream：回應嵌在 params.result.quote_updated
  - BuildSwap 是 unary RPC：用 JSON-RPC request，回應在 top-level result
    （SDK ApiClient.send → JSONRPCClient.request）

Usage:
    .venv/bin/python spike/omniston/build_swap_poc.py

Reproducible: 打 production wss://omni-ws.ston.fi，dump 完整回應到 stdout +
spike/omniston/build_swap_evidence.json。見 FINDINGS.md。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import websockets

# Production 跑 v1beta8。BuildSwap 不碰錢，安全打 production（與 M1 一致）。
DEFAULT_WS = "wss://omni-ws.ston.fi"
ENDPOINT = os.environ.get("OMNISTON_WS", DEFAULT_WS)

# JSON-RPC method names（SDK constants.ts）。
METHOD_QUOTE_SUBSCRIBE = "stonfi.omni.v1beta8.QuoteRpc.Quote"
METHOD_QUOTE_UNSUBSCRIBE = "stonfi.omni.v1beta8.QuoteRpc.Quote.unsubscribe"
METHOD_BUILD_SWAP = "stonfi.omni.v1beta8.TonRpc.BuildSwap"

# USDt jetton on TON mainnet（M1 已驗證可用）。
USDt_JETTON = "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs"

# 測試用錢包地址：隨便一個格式正確的 TON 地址即可——BuildSwap 只組 message，
# 不驗證地址餘額/所有權（那是 sendTransaction 那一步的事）。
# 用一個公開的、非個人的地址（TON 基金會 cold wallet 是公開已知地址）。
TRADER_ADDRESS = "EQDV8OoP-iqaGDncSOo0dAsPpS0KY_z-d1GraV8fArOy4L1g"

# 證據輸出路徑。
EVIDENCE_PATH = Path(__file__).parent / "build_swap_evidence.json"


def native_ton_asset() -> dict[str, Any]:
    return {"ton": {"native": {}}}


def jetton_asset(address: str) -> dict[str, Any]:
    return {"ton": {"jetton": address}}


def build_quote_request(req_id: str) -> dict[str, Any]:
    """v1beta8 Quote subscribe 請求（1 TON → USDt）。複用 M1 協議。"""
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": METHOD_QUOTE_SUBSCRIBE,
        "params": {
            "input_asset": native_ton_asset(),
            "output_asset": jetton_asset(USDt_JETTON),
            "input_units": "1000000000",  # 1 TON
            "settlement_params": [{"swap": {"max_price_slippage_pips": 10000}}],  # 1%
        },
    }


def build_swap_request(req_id: str, quote_id: str) -> dict[str, Any]:
    """v1beta8 BuildSwap unary RPC 請求。

    wire format（reverse-engineered from SDK BuildTonSwapRequest.toJSON +
    ChainAddress.toJSON）：
      - quote_id: 字串（來自上一步 Quote）
      - *_address: ChainAddress 的 JSON 是「裸扁平」{"ton": "<addr>"}，
        不是巢狀 {$case, value}（這是 ts-proto oneof 的 JSON 慣例）。
      - use_recommended_slippage: bool，用 Omniston 建議滑價（最安全）。
    """
    ton_addr = {"ton": TRADER_ADDRESS}
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": METHOD_BUILD_SWAP,
        "params": {
            "quote_id": quote_id,
            "transfer_src_address": ton_addr,
            "trader_dst_address": ton_addr,
            "gas_excess_address": ton_addr,
            "refund_src_address": ton_addr,
            "use_recommended_slippage": True,
        },
    }


async def fetch_quote_id(ws, timeout: float) -> str | None:
    """訂閱 Quote stream，拿到第一個 quote 的 quote_id，unsubscribe，回傳。"""
    await ws.send(json.dumps(build_quote_request(req_id="1")))
    print("[sent] Quote subscribe, 等待 quote_id...")

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 6))
        except asyncio.TimeoutError:
            continue

        msg = json.loads(raw)
        if isinstance(msg, dict) and "error" in msg:
            print(f"[err] Quote error: {msg['error']}")
            return None

        # Quote stream：回應嵌在 params.result.quote_updated
        result = (msg.get("params") or {}).get("result", {})
        if "quote_updated" in result:
            quote = result["quote_updated"]
            quote_id = quote.get("quote_id", "")
            # 乾淨 unsubscribe（best-effort）
            try:
                await ws.send(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": "2",
                            "method": METHOD_QUOTE_UNSUBSCRIBE,
                            "params": {},
                        }
                    )
                )
            except Exception:  # noqa: BLE001
                pass
            print(f"[ok] quote_id = {quote_id[:24]}...")
            return quote_id

    print("[fail] Quote 逾時，沒拿到 quote_id")
    return None


async def call_build_swap(ws, quote_id: str, timeout: float = 15.0) -> dict[str, Any] | None:
    """unary RPC：BuildSwap。回應在 top-level result（不是 stream 的 params.result）。"""
    req = build_swap_request(req_id="3", quote_id=quote_id)
    print(f"\n[sent] BuildSwap request:\n{json.dumps(req, indent=2)}")

    await ws.send(json.dumps(req))

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 6))
        except asyncio.TimeoutError:
            continue

        msg = json.loads(raw)
        print(f"\n[recv] {json.dumps(msg)[:300]}")

        # 只認 id=3 的回應（避開 Quote unsubscribe ack 等雜訊）
        if msg.get("id") != "3":
            continue

        if isinstance(msg, dict) and "error" in msg:
            print(f"\n[err] BuildSwap error: {json.dumps(msg['error'], indent=2)}")
            return {"_error": msg["error"]}

        # unary RPC：result 在 top level
        if "result" in msg:
            return msg["result"]

    print("[fail] BuildSwap 逾時")
    return None


def validate_message_for_send_transaction(tx: dict[str, Any]) -> list[str]:
    """驗證 message 格式能否被 tonConnectUI.sendTransaction 接受。

    對照 SDK example useTonTransaction.ts:76-87 的轉換邏輯：
      address ← target_address
      amount  ← send_amount
      payload ← hexToBase64(payload)        ← hex → base64 轉換
      stateInit ← hexToBase64(jetton_wallet_state_init?)

    回傳的 notes 裡，msg-level 的行以 "  ✅"/"  ❌"/"  ℹ️" 開頭（前面有縮排），
    摘要行以 "✅"/"❌" 開頭（無縮排）。判定 pass/fail 用 msg-level 行。
    """
    notes: list[str] = []
    messages = tx.get("messages", [])
    if not messages:
        notes.append("❌ messages 為空——BuildSwap 沒產出任何 message")
        return notes

    notes.append(f"✅ 收到 {len(messages)} 個 message")
    for i, m in enumerate(messages):
        prefix = f"  msg[{i}]"
        if not m.get("target_address"):
            notes.append(f"{prefix} ❌ 缺 target_address")
        else:
            notes.append(f"{prefix} ✅ target_address: {m['target_address'][:20]}...")
        if not m.get("send_amount"):
            notes.append(f"{prefix} ❌ 缺 send_amount")
        else:
            notes.append(f"{prefix} ✅ send_amount: {m['send_amount']} nanoTON")
        payload = m.get("payload", "")
        if not payload:
            notes.append(f"{prefix} ❌ 缺 payload（BoC hex）")
        elif not _is_hex(payload):
            notes.append(f"{prefix} ❌ payload 不是 hex：{payload[:30]}...")
        else:
            # 實際做一次 hex→base64 轉換，證明 sendTransaction 的 payload 欄位可用。
            b64 = _hex_to_base64(payload)
            notes.append(
                f"{prefix} ✅ payload: hex {len(payload)} chars → base64 {len(b64)} chars "
                f"({len(payload) // 2} bytes BoC)，可直接餵給 sendTransaction"
            )
        si = m.get("jetton_wallet_state_init")
        if si:
            notes.append(f"{prefix} ℹ️ 有 stateInit（jetton wallet 首次部署）")
    return notes


def _hex_to_base64(hex_str: str) -> str:
    """SDK example 的 hexToBase64 等價實作（tonConnectUI 要 base64 payload）。"""
    import base64

    return base64.b64encode(bytes.fromhex(hex_str)).decode("ascii")


def _is_hex(s: str) -> bool:
    if not s:
        return False
    try:
        int(s, 16)
        return True
    except ValueError:
        return False


async def run() -> int:
    print("=" * 72)
    print("Omniston BuildSwap Spike — v1beta8 (READ-ONLY, 不簽章不上鏈)")
    print("=" * 72)
    print(f"Endpoint: {ENDPOINT}")
    print("Trade:    1.0 native TON → USDt")
    print(f"Trader:   {TRADER_ADDRESS}")
    print(f"Python:   {sys.version.split()[0]}")
    print("⚠️  BuildSwap 只組未簽章 message，不碰私鑰、不上鏈。風險 = 0。")

    evidence: dict[str, Any] = {
        "spike": "M3 BuildSwap",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "endpoint": ENDPOINT,
        "trade": "1 TON → USDt",
        "trader_address": TRADER_ADDRESS,
    }

    try:
        async with websockets.connect(
            ENDPOINT,
            open_timeout=25.0,
            close_timeout=5,
            additional_headers={"Origin": "https://ston.fi"},
        ) as ws:
            # STEP 1: Quote → quote_id
            print("\n── STEP 1: Quote → quote_id ──")
            quote_id = await fetch_quote_id(ws, timeout=25.0)
            if not quote_id:
                print("\n❌ 拿不到 quote_id，後續無法測 BuildSwap。")
                evidence["error"] = "no_quote_id"
                EVIDENCE_PATH.write_text(json.dumps(evidence, indent=2))
                return 1
            evidence["quote_id"] = quote_id

            # STEP 2: BuildSwap → TonTransaction
            print("\n── STEP 2: BuildSwap → message body ──")
            tx = await call_build_swap(ws, quote_id, timeout=15.0)
            if tx is None:
                print("\n❌ BuildSwap 無回應。")
                evidence["error"] = "build_swap_no_response"
                EVIDENCE_PATH.write_text(json.dumps(evidence, indent=2))
                return 1
            evidence["build_swap_response"] = tx

            if "_error" in tx:
                print("\n❌ BuildSwap 被 server 拒絕（這本身是有價值的發現）：")
                print(json.dumps(tx["_error"], indent=2))
                EVIDENCE_PATH.write_text(json.dumps(evidence, indent=2))
                return 2  # 非 0：server 拒絕也是一種結果，但不算成功

    except websockets.exceptions.InvalidStatus as e:
        print(f"\n[fail] connection refused: HTTP {e.response.status_code}")
        evidence["error"] = f"connection_refused_{e.response.status_code}"
        EVIDENCE_PATH.write_text(json.dumps(evidence, indent=2))
        return 1
    except (OSError, websockets.exceptions.WebSocketException) as e:
        print(f"\n[fail] {type(e).__name__}: {e}")
        evidence["error"] = f"{type(e).__name__}: {e}"
        EVIDENCE_PATH.write_text(json.dumps(evidence, indent=2))
        return 1

    # STEP 3: 驗證格式相容 sendTransaction
    print("\n── STEP 3: 驗證 message 能否被 sendTransaction 接受 ──")
    notes = validate_message_for_send_transaction(tx)
    for n in notes:
        print(n)
    evidence["validation"] = notes

    EVIDENCE_PATH.write_text(json.dumps(evidence, indent=2, ensure_ascii=False))

    print("\n" + "=" * 72)
    # 判定：msg-level 行（有縮排 "  ✅"/"  ❌"）全部必須是 ✅。
    msg_notes = [n for n in notes if "msg[" in n]
    all_ok = bool(msg_notes) and not any("❌" in n for n in msg_notes)
    if all_ok:
        print("✅ BUILD_SWAP_SPIKE 通過 — BuildSwap 能產出可簽章 message body")
        print(f"   證據：{EVIDENCE_PATH}")
        return 0
    print("⚠️  BuildSwap 有回應但格式待確認，見證據檔。")
    return 2


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
