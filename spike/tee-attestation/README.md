# TEE 可驗證執行 spike（D）

證明「agent 的風險評估發生在可信硬體（TEE）內、可被外部密碼學驗證」——
這是可驗證性三件套的最後一塊（A 開源內核 + B 版本綁定 + C 同意足跡 +
**D 執行證明**）。

## 架構

```
外部審查員                     TEE（Phala Cloud）                主平台（閉源）
   │                                │                                │
   │  quote.json ──────────────►    │                                │
   │                                │  safety_kernel.assess_risk     │
   │  ◄── report.json +            │  （開源規則，純函式）            │
   │      attestation.json          │                                │
   │                                │                                │
   │  驗證：hash 重算 + kernel 版本  │                                │
   │  + TEE 簽章鏈                  │                                │
```

- 資產層留在 TON（Omniston swap，已上線）；執行層（風險評估、之後的
  BYOK 私鑰處理）進 TEE。
- 審查員不需要主平台原始碼：attestation 證明「規則 vX.Y.Z 真的照跑」。

## 本機模擬（不需要 TEE 帳號就能測 spike 邏輯）

```bash
# 1. 產生報告（safety_kernel 已裝在主平台 venv）
.venv/bin/python spike/tee-attestation/assess_in_tee.py \
    spike/tee-attestation/sample_quote.json > /tmp/report.json

# 2. 驗證報告（hash + 版本 + 結構）
.venv/bin/python spike/tee-attestation/verify_report.py /tmp/report.json
```

## 部署到真實 TEE（需要 DANNY 操作的外部帳號步驟）

1. **註冊 Phala Cloud**（https://cloud.phala.network）— 新帳號免費點數；
   亦可申請 Phala Privacy AI Startup Program（$1,000 雲端點數 + 工程支援，
   48 小時回覆、無股份）。
2. **建 image**：`docker build -f spike/tee-attestation/Dockerfile .`
   （需先把 safety_kernel/ 放到 spike/tee-attestation/ 內或改 COPY 路徑）
3. **部署**：Phala Cloud 網頁上傳 image，或 `phala-cloud` CLI。
4. **拿 attestation**：平台回傳 TEE 證書，存成 `attestation.json`：
   ```json
   {"attestation": "<platform-signed-blob>", "report_hash": "<facts_hash>"}
   ```
5. **驗證**：`python verify_report.py report.json attestation.json`

## 驗證成功標準

- [ ] report 的 `kernel_version` == 公開 repo 的 tag
- [ ] `input_hash` 與原始 quote.json 的 sha256 一致
- [ ] attestation 由 Phala/Intel 簽章鏈驗證通過
- [ ] 竄改測試：改過 rules 再跑 → hash 對不上 → 驗證失敗

## 後續（spike 通過後）

- 完整 agent 執行（BYOK key 管理、提示詞）搬進 TEE → Oasis（Sapphire +
  ROFL）申請主體（Oasis 資助過 Omo Protocol：TEE 內管 agent 私鑰做
  DeFi 策略，與 CryptoMind 同題材）
- 設計文件：docs/plans/2026-08-07-tee-verifiable-execution-design.md
