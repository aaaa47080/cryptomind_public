# AGENTS.md — scripts/

> CI/CD + ops scripts (54 files). See root `AGENTS.md` for stack / anti-pattern common rules.

## SCRIPT CATEGORIES (54 files)

| Category | Key scripts |
|----------|-------------|
| Quality gates | `run_autonomous_policy_checks.sh`, `security-check.sh`, `post_deploy_smoke.sh` |
| DB ops | `migrate.py`, `migrate_production_db.py`, `migrate_db_legacy.py`, `migrate_tool_tiers.py`, `add_indexes.py`, `reset_db.py`, `setup_test_db.py`, `sync_prod_db.py`, `backup.sh` |
| Static asset / cache | `check_static_refs.py`, `check_asset_versions.py`, `clear_market_pulse_cache.py`, `refresh_lock_and_audit.sh` |
| Cron jobs | `cron_expire_members.py` (PRO expiry), `cron_governance.py` (vote tally), `market_pulse_worker.py` |
| Data / cleanup | `clean_dependencies.py`, `clean_unused_files.py`, `delete_unused_files.sh`, `delete_all_posts.py`, `delete_user_posts.py`, `purge_git_history.{sh,bat}`, `check_secrets.py`, `check_wallet_status.py`, `verify_*.py`, `update_readme.py` |
| Dev runners | `run_analyzer.sh`, `run_cloudflare.{sh,bat}`, `run_ngrok.sh`, `stop_server.sh`, `test_health.sh` |
| Standalone tests | `test_agent_integration.py`, `test_multilingual.py`, `test_us_stock.py`, `test_usstock_board.py`, `create_test_forum_post.py` |

## CRITICAL GATES

- **Before commit**: `run_autonomous_policy_checks.sh`, `security-check.sh`, `check_secrets.py`, `check_static_refs.py`, `check_asset_versions.py`
- **After deploy**: `post_deploy_smoke.sh` (requires `API_URL=https://...`)
- **Weekly**: `refresh_lock_and_audit.sh` (pip-audit + lockfile refresh)

## KEY PATTERNS

- **Smoke scripts** (`.sh`): `curl` + `grep` to verify endpoints + content, fail-fast
- **DB migrations**: `migrate.py` is the main entry, `migrate_production_db.py` for prod (dry-run + confirmation)
- **Cron scripts**: called directly by systemd timer / cron job, must be idempotent
- **Standalone tests** (in `scripts/`, not `tests/`): manual smoke / staging environment use

## ANTI-PATTERNS

- `purge_git_history.sh` / `.bat` — rewrites git history, highly destructive, **use only when you confirm you want to break all clones**, must back up before running
- `delete_all_posts.py` / `delete_user_posts.py` — deletes DB rows directly, requires backup + dry-run flag
- `migrate_production_db.py` — changes prod schema directly, always run dry-run first
- Multiple scripts hardcode paths and don't accept env overrides → must ask DANNY before changing

## TOP FILES BY IMPORTANCE

1. `run_autonomous_policy_checks.sh` — integrated gate for autonomous data policies
2. `security-check.sh` — security gate
3. `migrate.py` + `migrate_production_db.py` — schema change entry
4. `post_deploy_smoke.sh` — deploy verification
5. `check_secrets.py` — prevents hardcoded secrets from entering the repo
6. `check_static_refs.py` + `check_asset_versions.py` — asset integrity
7. `cron_expire_members.py` + `cron_governance.py` — automated business logic

## SEE ALSO

- Root `AGENTS.md` — Quick commands reference these scripts
- `tests/AGENTS.md` — pytest tests vs standalone integration here
- `.github/workflows/` — 6 CI workflows also call some scripts
