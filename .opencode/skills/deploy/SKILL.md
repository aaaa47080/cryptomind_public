---
name: deploy
description: Deploy to Zeabur staging via develop branch — NEVER push to main directly
---

## CRITICAL RULE

**永遠推到 `develop`，絕對不要直接推到 `main`。**

| Branch | 用途 | 誰可以 merge |
|--------|------|-------------|
| `develop` | 測試/預覽，Zeabur 自動部署 | AI 可以（需 CI 全綠） |
| `main` | 主網 production | **只有 DANNY 手動 merge** |

## 正確流程

### 1. 從 develop 建立 feature branch

```bash
git fetch origin
git checkout -b fix/xxx origin/develop
```

### 2. Commit + Push branch

```bash
git add -A && git commit -m "fix/feat/..."
git push origin fix/xxx
```

### 3. 建立 PR → develop（不是 main）

```bash
gh pr create --base develop --head fix/xxx --title "..." --body "..."
```

### 4. 等 CI 全綠才能 merge

```bash
gh pr checks <PR_NUMBER> --watch
```

必須全部 pass：lint, test, e2e-tests, python-tests, validate-json

### 5. Squash merge + 刪 branch

```bash
gh pr merge <PR_NUMBER> --squash --delete-branch
```

### 6. Zeabur 自動部署

Merge 後 Zeabur 偵測 develop 更新 → 自動 build + deploy。

## 絕對不要做的事

- ❌ `git push origin main` — 不會觸發 Zeabur
- ❌ 在 main 上直接 commit
- ❌ 建立 PR → main（除非 DANNY 明確要求）
- ❌ CI 還沒全綠就 merge

## 前端 build 驗證

```bash
npm run build          # Vite build 必須通過
ruff check .           # Python lint
ruff format --check .  # Python format
python3 scripts/check_i18n_keys.py  # i18n key 對齊
```
