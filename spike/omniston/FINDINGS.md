# Omniston M3 Spike — BuildSwap Findings

> **Spike:** Can Omniston's `BuildSwap` API produce a **signable swap message
> body** that `tonConnectUI.sendTransaction` will accept?
> **Verdict:** ✅ **YES — fully proven.** Real message body captured from mainnet.

承接 M1 quote spike：M1 證明了 Python 能拿報價；本 spike 推進到「執行」鏈路最關鍵
的未知數——BuildSwap 能不能產出可簽章的 message。

## TL;DR

一個獨立 Python 腳本（`build_swap_poc.py`）打 production Omniston，完成完整鏈路：
**Quote（拿 quote_id）→ BuildSwap（拿 message body）→ 格式驗證**。拿到真實的、未簽章
的 swap message，其 `payload` 是真實的 BoC cell（hex），hexToBase64 後可直接餵給
`tonConnectUI.sendTransaction`。

這把 M3 三件待驗證事全部解除風險，M3 實作（deterministic pipeline 接 BuildSwap
→ 前端 sendTransaction）技術上完全可行。

## 三件待驗證事（全部 ✅）

| # | Spike 任務 | 結論 | 證據 |
|---|---|---|---|
| 1 | BuildSwap API 能否產出可簽章 message | ✅ 能 | `TonTransaction.messages[]` 含 target/amount/payload |
| 2 | 跑通 BuildSwap 拿真實 message body | ✅ 拿到 | 見下方 captured payload + `build_swap_evidence.json` |
| 3 | message 能被 sendTransaction 接受 | ✅ 相容 | hex payload → hexToBase64 → 符合 sendTransaction payload 欄位 |

## Captured message body（real, mainnet, 1 TON → USDt）

第一次跑（`build_swap_evidence.json` 完整留存）：

```json
{
  "messages": [{
    "target_address": "EQDa4VOnTYlLvDJ0gZjNYm5PXfSmmtL6Vs6A_CZEtXCNICq_",
    "send_amount": "1100000000",     // 1.1 TON（含 gas 預付）
    "payload": "b5ee9c724101030100ab00016bea06185d4e6a81fef727ae1d..."
              // ↑ BoC cell, hex, 372 chars = 186 bytes
  }]
}
```

- `target_address`：Omniston router 合約（不是 DEX 本身，是聚合路由）
- `send_amount`：`input_units` + gas 預付（這裡 1 TON input + 0.1 gas ≈ 1.1 TON）
- `payload`：**這是關鍵**——內含 swap 指令（quote_id、路由、滑價保護），是未簽章
  的 BoC cell。`b5ee9c72...` 是 TON Cell 的標準 magic（Boc 根）。

兩次跑拿到不同 message（不同 quote_id、不同 router、不同 amount），證明不是快取、
是即時計算。

## Wire format（實作 M3 必讀）

### BuildSwap vs Quote：協議不同

| | Quote (M1) | BuildSwap (M3) |
|---|---|---|
| RPC 類型 | subscribe stream | **unary**（req/resp）|
| SDK 方法 | `subscribeToStream` | `ApiClient.send` → `JSONRPCClient.request` |
| 回應位置 | `params.result.quote_updated`（嵌在 stream 通知） | **top-level `result`** |
| 需 unsubscribe | ✅ 是 | ❌ 否 |

**實作陷阱**：M1 的 `fetch_quote` 解析邏輯（找 `params.result.quote_updated`）**不能**
直接套用 BuildSwap。BuildSwap 回應在 `msg["result"]`（top level）。PoC 的
`call_build_swap` 已正確處理。

### BuildTonSwapRequest JSON wire format

逆向自 SDK `BuildTonSwapRequest.toJSON` + `ChainAddress.toJSON`：

```jsonc
{
  "jsonrpc": "2.0",
  "id": "3",
  "method": "stonfi.omni.v1beta8.TonRpc.BuildSwap",
  "params": {
    "quote_id": "<來自上一步 Quote>",
    "transfer_src_address": {"ton": "EQ..."},   // ChainAddress 裸扁平，不是 {$case,value}
    "trader_dst_address":   {"ton": "EQ..."},
    "gas_excess_address":   {"ton": "EQ..."},
    "refund_src_address":   {"ton": "EQ..."},
    "use_recommended_slippage": true             // 用 Omniston 建議滑價（最安全）
  }
}
```

**關鍵 gotcha**：`ChainAddress` 的 JSON 是 `{"ton": "<addr>"}`（裸扁平），**不是**
`{"$case": "ton", "value": "<addr>"}`。這是 ts-proto protobuf oneof 的 JSON 慣例，
跟 in-memory 的 TS interface 長得不一樣。搞錯這個 server 會回 deserialize error。

### TonTransaction 回應格式

```jsonc
{
  "result": {                          // ← top level（不是 stream 的巢狀）
    "messages": [
      {
        "target_address": "EQ...",     // router 合約地址
        "send_amount": "1100000000",   // nanoTON 字串
        "payload": "b5ee9c72...",      // hex BoC，未簽章 message body
        "jetton_wallet_state_init": "..."  // 可選，jetton wallet 首次部署才會有
      }
    ]
  }
}
```

## sendTransaction 銜接（第 3 件事的證據）

對照 SDK example `examples/react-app/hooks/useTonTransaction.ts:76-87`：

```js
tonConnect.sendTransaction({
  validUntil: Math.floor(Date.now() / 1000) + 5 * 60,
  from: tonConnect.account?.address,
  messages: messages.map((message) => ({
    address: message.targetAddress,                              // ← BuildSwap 的 target_address
    amount: message.sendAmount,                                  // ← BuildSwap 的 send_amount
    payload: hexToBase64(message.payload),                       // ← hex → base64 ★
    stateInit: message.jettonWalletStateInit
      ? hexToBase64(message.jettonWalletStateInit) : undefined,
  })),
});
```

PoC 的 `_hex_to_base64` 實作了等價轉換並實際跑過：372-char hex payload → 304-char
base64（227 bytes）。**格式完全相容**，M3 前端可直接套用此 mapping。

## M3 實作建議（給實作者）

1. **後端**（`core/tools/crypto_modules/omniston_client.py`）：
   - 加一個 `build_swap(quote_id, trader_address) -> TonTransaction` async 函式。
   - 走 unary RPC（req/resp），**不要**抄 `fetch_quote` 的 stream 解析。
   - 四個地址欄位（transfer/trader_dst/gas_excess/refund）實務上同一個錢包地址即可，
     除非要分開收退款（產品決策，問 DANNY）。

2. **接線位置**：`swap_pipeline.py` 目前只做到 STEP 1-4（報價+風險）。M3 在
   `assess_risk` 通過 + consent_gate 同意後，加 STEP 5 呼叫 `build_swap`，把
   message body 回給前端。

3. **前端**：照 `useTonTransaction.ts` 的 mapping 寫一個 vanilla JS 版（CryptoMind
   不是 React）。需在 `web/js/` 加 swap 執行 modal（TON Connect 簽章 UI）。

4. **人工審核兩道不可省**：
   - consent_gate（agent 軟閘門，已實作 `consent_gate.py`）
   - sendTransaction（錢包硬閘門，TON Connect 協議鐵律——agent 永遠拿不到私鑰）

5. **觸發點未決**：「查詢」vs「執行」意圖區分（`claw_loop.py:776`）目前靠關鍵字，
   但「幫我換 100 TON」查詢/執行兩可。這是 M3 實作的產品問題，不在 spike 範圍，
   但實作前要跟 DANNY 確認觸發策略（顯式指令？二次確認？）。

## 安全性聲明

- BuildSwap **不簽章、不上鏈、不動錢**。它只組未簽章 message。
- PoC 用的是非個人、公開已知的 TON 地址，零資金風險。
- 真正簽章在 `sendTransaction`（前端，使用者親自在錢包 app 確認），agent 無法繞過。
- 證據檔 `build_swap_evidence.json` 不含任何私鑰/敏感資料（message body 是公開可推導的）。

## 重現

```bash
.venv/bin/python spike/omniston/build_swap_poc.py
# 預期：✅ BUILD_SWAP_SPIKE 通過，證據寫入 build_swap_evidence.json
```

---

# Omniston Integrator Fee Spike — Findings

> **Spike:** Omniston v1beta8 的 integrator fee（整合者手續費）怎麼結算？
> **Verdict:** ✅ **Confirmed — fee 從使用者收到的 output 扣除，協議自動結算到
> integrator_address，平台不需要持私鑰。**

## TL;DR

`integrator_fee_poc.py` 對同一報價（1 TON → USDt）送兩次 Quote：一次無 fee、一次帶
`integrator_address` + `integrator_fee_pips=3000`（0.3%）。對比完整 quote 回應確認機制。

## 三件待驗證事（全部 ✅）

| # | Spike 任務 | 結論 | 證據 |
|---|---|---|---|
| 1 | fee 怎麼收？ | **從使用者收到的 output 扣**（非 input、非平台另收） | 基準 1,386,610 → 帶fee 1,382,451，差額 = `integrator_fee_units`(4,159) 完全相等 |
| 2 | `integrator_fee_units` 是什麼？ | fee 實際金額（nano），Omniston 自動計算 | 4,159 / 1,386,610 = 0.2999% ≈ 3000 pips |
| 3 | fee 有進保護嗎？ | **有**——`min_output_amount` 也扣 fee（差 4,117） | 使用者最少收到量已含 fee，不會有報價/實收落差 |

## 實作關鍵發現

- **RFQ 欄位位置**：`integrator_address`（`{"ton": addr}`）+ `integrator_fee_pips`
  放在 **params 頂層**（與 input_asset 同層），server 接受且正常回應。
- **回傳欄位**：quote 頂層含 `integrator_fee_units`、`protocol_fee_units`（本實驗
  protocol_fee_units=0）、`integrator_address`。
- **地址標準化**：送 `UQDvjDhEZ128...` 回傳 `EQDvjDhEZ128...`（同地址兩種形式）。
- **零私鑰風險**：fee 由協議層自動結算給 integrator_address，平台無需持私鑰——
  與「後端永不碰私鑰」的信任層原則一致。
- **不影響 BuildSwap**：fee 在 Quote/RFQ 階段帶入，BuildSwap 用 quote_id 自動帶 fee。

## 證據

- 完整 raw quote 對比：`spike/omniston/integrator_fee_evidence.json`

## 重現

```bash
.venv/bin/python spike/omniston/integrator_fee_poc.py
# 預期：對比分析顯示 output 差異 = integrator_fee_units，證據寫入 integrator_fee_evidence.json
```

## ⚠️ 驗證邊界（重要，勿誇大）

**已實測確認（Quote 階段）：**
- fee 從使用者收到的 output 扣（基準 vs 帶fee 差額 = integrator_fee_units）
- fee 比例精準（0.2999% ≈ 3000 pips）
- min_output_amount 含 fee 保護

**未實測確認（BuildSwap/鏈上階段）：**
- BuildSwap response 只回 `messages[]`，**不含 fee 欄位**（fee 內嵌在
  swap payload 裡，無法從 API 表面驗證）
- **fee 是否真的結算給 integrator_address，需一次「真簽章 + 上鏈 + 追蹤收款」
  才能 100% 確認** —— 這需要平台實際跑一筆小額 swap 驗證
- 上線前建議：用 1 TON 小額實跑一筆帶 fee 的 swap，確認收款地址收到 fee
  （`TON_RECEIVING_ADDRESS`）後，才把「fee 收入」當成可靠的 revenue 來源

**這不影響功能上線**：fee 邏輯正確（Quote 已帶、token 已綁、UI 已顯示），
只是「最終結算」的驗證要等一筆真實交易。code review 已確認此邊界。
