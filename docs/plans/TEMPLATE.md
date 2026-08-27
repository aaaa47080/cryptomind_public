# Feature Spec Template

> **使用時機**：任何觸發根 `AGENTS.md`「須先確認」清單的變更——
> schema migration、登入/權限模型、TON 收款/價格邏輯、新 agent、新外部服務、破壞性維運。
>
> **不需要本模板的**：明確 bug 修復、安全加固、輸入驗證、測試、文案、CSS 微調——這些直接做。
>
> **填寫範例**：見 `2026-02-26-us-stock-agent-and-price-alerts-design.md`（design）與 `-impl.md`（implementation）。

---

## 如何使用本模板

1. 複製本檔，命名 `YYYY-MM-DD-<topic>-design.md`（design）+ `-impl.md`（implementation plan）。
2. **先寫 design**，跟 DANNY 確認後再寫 impl。
3. Design 討論定案後，Status 改 `Approved`，才開始實作。
4. 實作期間 design 若有實質變更，回頭更新 design 檔（不要讓檔案與實作脫鉤）。

---

# Design: <功能名稱>

| 欄位 | 值 |
|---|---|
| Date | YYYY-MM-DD |
| Status | Draft / Approved / Implemented / Superseded |
| Branch | `<branch-name>` |
| PR | #NNN（實作時補） |

## 決策門檻（勾選觸發項）

本功能是否觸發「須先確認」清單？（見根 `AGENTS.md` 授權界線）

- [ ] Schema migration
- [ ] 登入 / 權限模型變更
- [ ] TON 收款 / 價格邏輯
- [ ] 新 agent
- [ ] 新外部服務
- [ ] 破壞性維運腳本
- [x] 以上皆非——可直接實作，本檔僅作規劃記錄

> **若有勾選**：本 design 必須經 DANNY 確認 Status = Approved 才能動手。

## Overview

一段話說明要蓋什麼、為什麼現在蓋。使用者或系統面臨什麼問題，本功能如何解決。

## Problem

具體描述現況的痛點。如果可能，附上：
- production trace / log 證據（Langfuse trace ID、錯誤訊息）
- 使用者報告原文
- 量化的影響（影響多少使用者、發生頻率）

不要只寫「體驗不好」——要寫「使用者在 X 場景遇到 Y，導致 Z」。

## Architecture Changes

### 現況（Before）
目前相關程式碼如何運作。列涉及的主要檔案與資料流。

### 目標（After）
改完後如何運作。標示新增 / 修改 / 移除的元件。

### 方案選擇
至少列 2 個可行方案，簡述取捨。為什麼選 A 不選 B。

## 影響面

| 面向 | 影響 |
|---|---|
| 資料庫 | 是否需要 migration？schema 變更？ |
| API | 新增 / 變更 endpoint？合約是否向下相容？ |
| 前端 | 哪些 tab / 元件受影響？ |
| Agent / prompt | 是否動到 `shared.yaml`？需 4 語同步？ |
| 安全 | 新增攻擊面？認證 / 授權 / rate limit 是否到位？ |
| 部署 | 新環境變數？新服務？資源需求？ |

## 風險與回滾

- **主要風險**：什麼可能出錯？最壞情況？
- **回滾方案**：若上線後出問題，如何快速還原（feature flag / DB migration down / ...）。

## 測試策略

- 單元測試覆蓋哪些路徑（成功 / 拒絕 / 邊界）
- 整合 / E2E 情境
- （若改 agent 行為）`tests/scenarios/run_suite.py` 情境集

---

# Implementation Plan: <功能名稱>

> Design 經 Approved 後才寫本段。

## Goal
一句話：本次實作要交付什麼。

## Tech Stack
涉及的主要技術與既有模式（例如：FastAPI router + async SQLAlchemy、Vanilla JS tab renderer）。

## Part A: <子任務群組名稱>

### Task A1: <任務名稱>
**Files:** `path/to/file.py`, `path/to/test.py`
**Context:** 為什麼需要這個任務，它銜接前後哪個任務。
**Steps:**
1. ...
2. ...
3. ...

### Task A2: ...

## Part B: <子任務群組名稱>

### Task B1: ...

## 驗證 Checklist

實作完成後，依序跑：
- [ ] `.venv/bin/python -m ruff check <changed_files>`
- [ ] `.venv/bin/python -m pytest -m "not e2e" --tb=short --no-cov`
- [ ] `.venv/bin/python scripts/check_secrets.py`
- [ ] （若改 agent）`tests/scenarios/run_suite.py` 8+ scenario 通過
- [ ] （若改前端）`npm run build:css` + 瀏覽器實測
- [ ] （若改 prompt）4 語 governance test 通過

## 部署 Checklist

- [ ] 環境變數已備妥（列出具體 key）
- [ ] migration 已在 staging 驗證
- [ ] 回滾方案已確認可行

---

## 參考

- 根 `AGENTS.md` — 授權界線與安全基線
- `docs/development_workflow.md` — agent 開發 SOP（含 commit/PR 流程）
- `docs/DESIGN_SYSTEM.md` — 前端視覺決策（若本功能涉及 UI）
