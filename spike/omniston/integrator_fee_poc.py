"""Omniston integrator fee spike — 確認 fee 結算機制 (v1beta8)。

M2 spike：在瞭解 integrator fee「怎麼收、收到哪」之前，不寫實作 code。
這個 PoC 對同一組報價請求送兩次 Quote——一次不帶 fee、一次帶 integrator
fee——dump 完整 quote 回應對比，回答三個問題：

  1. fee 是自動轉到 integrator_address，還是從 input_units 扣，還是鏈上分配？
  2. integrator_fee_units / protocol_fee_units 回傳值代表什麼？
  3. 帶 fee 後 output_units / min_output_amount 怎麼變化？

READ-ONLY：只送 Quote subscribe（不 BuildSwap、不簽章、不上鏈、不動錢）。
跟 M1/M3 spike 一樣安全地打 production WS。

Usage:
    .venv/bin/python spike/omniston/integrator_fee_poc.py

輸出：stdout 完整對比 + spike/omniston/integrator_fee_evidence.json。
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

# Production 跑 v1beta8。Quote 是 read-only，安全打 production（與 M1/M3 一致）。
DEFAULT_WS = "wss://omni-ws.ston.fi"
ENDPOINT = os.environ.get("OMNISTON_WS", DEFAULT_WS)

METHOD_QUOTE_SUBSCRIBE = "stonfi.omni.v1beta8.QuoteRpc.Quote"
METHOD_QUOTE_UNSUBSCRIBE = "stonfi.omni.v1beta8.QuoteRpc.Quote.unsubscribe"

USDt_JETTON = "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs"

# integrator_address：用平台既有收款地址（mainnet）。
# 注意：Quote 是 read-only， integrator_address 只是被放進 RFQ 看回傳，
# 不會真的把錢轉過去（那是 BuildSwap + 簽章才會發生）。
INTEGRATOR_ADDRESS = "UQDvjDhEZ128EktbSBrK4CWrw1xTTbx4ojlZ-rF2OOS2H6Db"

EVIDENCE_PATH = Path(__file__).parent / "integrator_fee_evidence.json"


def native_ton_asset() -> dict[str, Any]:
    return {"ton": {"native": {}}}


def jetton_asset(address: str) -> dict[str, Any]:
    return {"ton": {"jetton": address}}


def build_quote_request(req_id: str, *, with_fee: bool) -> dict[str, Any]:
    """v1beta8 Quote subscribe 請求（1 TON → USDt）。

    with_fee=False：基準（無 fee），對照組。
    with_fee=True：帶 integrator_address + integrator_fee_pips，實驗組。
    """
    params: dict[str, Any] = {
        "input_asset": native_ton_asset(),
        "output_asset": jetton_asset(USDt_JETTON),
        "input_units": "1000000000",  # 1 TON
        "settlement_params": [{"swap": {"max_price_slippage_pips": 10000}}],  # 1%
    }
    if with_fee:
        # 文件只說「integrator_address, integrator_fee_pips on the RFQ」，
        # 沒明確說在頂層還是 settlement_params 內。先試頂層（最直覺）。
        # 若 server 報錯，再試放進 settlement_params[0]["swap"] 內。
        params["integrator_address"] = {"ton": INTEGRATOR_ADDRESS}
        params["integrator_fee_pips"] = 3000  # 0.3%
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": METHOD_QUOTE_SUBSCRIBE,
        "params": params,
    }


async def fetch_one_quote(ws: Any, request: dict[str, Any], deadline: float) -> dict[str, Any]:
    """送 quote subscribe，等第一個 quote_updated event，回完整 raw quote。"""
    await ws.send(json.dumps(request))
    req_id = request["id"]
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise TimeoutError(f"quote {req_id} 逾時")
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 8.0))
        except asyncio.TimeoutError:
            continue
        msg = json.loads(raw)
        # JSON-RPC error
        if "error" in msg:
            raise RuntimeError(f"server error: {json.dumps(msg['error'], ensure_ascii=False)}")
        # quote_updated 事件
        result = msg.get("params", {}).get("result", {})
        if "quote_updated" in result:
            # best-effort unsubscribe（別讓 subscription 殘留）
            try:
                await ws.send(json.dumps({
                    "jsonrpc": "2.0",
                    "id": "unsub-" + req_id,
                    "method": METHOD_QUOTE_UNSUBSCRIBE,
                    "params": {"id": result.get("rfq_id", "")},
                }))
            except Exception:
                pass
            return result["quote_updated"]
    # unreachable


async def main() -> int:
    print(f"[fee-spike] endpoint = {ENDPOINT}")
    evidence: dict[str, Any] = {"timestamp": int(time.time()), "endpoint": ENDPOINT}

    try:
        async with websockets.connect(
            ENDPOINT,
            open_timeout=15,
            close_timeout=5,
            additional_headers={"Origin": "https://ston.fi"},
        ) as ws:
            # 1. 基準：無 fee
            print("\n=== [1/2] 基準 quote（無 integrator fee）===")
            base_req = build_quote_request("base", with_fee=False)
            print(f"request params keys: {list(base_req['params'].keys())}")
            base_deadline = time.time() + 20
            try:
                base_quote = await fetch_one_quote(ws, base_req, base_deadline)
                print(f"✓ quote_id = {base_quote.get('quote_id', '')[:24]}...")
                print(f"  output_units      = {base_quote.get('output_units')}")
                print(f"  min_output_amount = {base_quote.get('swap', {}).get('min_output_amount')}")
                print(f"  resolver          = {base_quote.get('resolver_name')}")
                evidence["baseline_quote"] = base_quote
            except (TimeoutError, RuntimeError) as exc:
                print(f"✗ 基準 quote 失敗: {exc}")
                evidence["baseline_error"] = str(exc)
                # 基準都失敗就別繼續
                EVIDENCE_PATH.write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
                return 1

            # 短暫等待，避免 WS 混亂
            await asyncio.sleep(1.0)

            # 2. 實驗：帶 fee
            print("\n=== [2/2] 實驗 quote（帶 integrator fee 0.3%）===")
            fee_req = build_quote_request("fee", with_fee=True)
            print(f"request params keys: {list(fee_req['params'].keys())}")
            print(f"  integrator_address = {fee_req['params']['integrator_address']}")
            print(f"  integrator_fee_pips = {fee_req['params']['integrator_fee_pips']}")
            fee_deadline = time.time() + 20
            try:
                fee_quote = await fetch_one_quote(ws, fee_req, fee_deadline)
                print(f"✓ quote_id = {fee_quote.get('quote_id', '')[:24]}...")
                print(f"  output_units        = {fee_quote.get('output_units')}")
                print(f"  min_output_amount   = {fee_quote.get('swap', {}).get('min_output_amount')}")
                print(f"  resolver            = {fee_quote.get('resolver_name')}")
                evidence["fee_quote"] = fee_quote
            except (TimeoutError, RuntimeError) as exc:
                print(f"✗ fee quote 失敗: {exc}")
                print("  → 可能 integrator_address 欄位位置錯，下一步試放進 settlement_params")
                evidence["fee_error"] = str(exc)
                EVIDENCE_PATH.write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
                return 2

            # 3. 對比分析
            print("\n=== 對比分析 ===")
            base_out = base_quote.get("output_units", "0")
            fee_out = fee_quote.get("output_units", "0")
            print(f"output_units: 基準={base_out}  帶fee={fee_out}")
            try:
                diff = int(fee_out) - int(base_out)
                print(f"  差異 = {diff}（負數 = fee 從使用者收到量扣）")
            except (ValueError, TypeError):
                print("  差異無法計算")

            # 找 fee 相關欄位（頂層 + swap 內）
            print("\n--- fee 相關欄位掃描 ---")
            for label, q in [("baseline", base_quote), ("fee", fee_quote)]:
                fee_fields: dict[str, Any] = {}
                for key in ("integrator_fee_units", "protocol_fee_units",
                            "integrator_fee_pips", "integrator_address"):
                    if key in q:
                        fee_fields[key] = q[key]
                    swap_obj = q.get("swap") or {}
                    if key in swap_obj:
                        fee_fields[f"swap.{key}"] = swap_obj[key]
                print(f"  [{label}] {fee_fields if fee_fields else '(無 fee 欄位)'}")

            # dump 完整 raw 供細查
            print(f"\n--- baseline quote 全部頂層 key ---\n  {list(base_quote.keys())}")
            print(f"--- fee quote 全部頂層 key ---\n  {list(fee_quote.keys())}")

            EVIDENCE_PATH.write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
            print(f"\n[evidence] 完整回應已存 {EVIDENCE_PATH}")
            return 0

    except Exception as exc:
        print(f"\n✗ spike 失敗: {type(exc).__name__}: {exc}")
        evidence["fatal_error"] = f"{type(exc).__name__}: {exc}"
        EVIDENCE_PATH.write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
        return 3


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
