#!/bin/sh
# Container entrypoint for the API service.
#
# Runs database migrations BEFORE starting the web server so the schema is
# always in sync with the deployed code. This prevents the failure mode where
# new code references a column/table that a not-yet-applied migration would
# have added (which silently breaks queries and takes features offline).
#
# gunicorn runs with workers=1 and preload_app=False, so this entrypoint runs
# exactly once per container start — no risk of workers racing on alembic.
#
# Best-effort: migrations are idempotent, but a migration failure must NOT
# crashloop the whole API (the core schema is also ensured by init_db at app
# startup). We log loudly and start the server anyway, so a migration glitch
# degrades gracefully instead of taking the service down.

# 關鍵 schema 直接保底（不依賴 alembic 成功、也不依賴 init_db reconcile）：
#  1) 加寬 alembic_version.version_num —— alembic 預設建成 VARCHAR(32)，本專案用
#     描述式 revision id（c005_add_active_session_to_telegram=35 字元）超過 32 時，
#     寫回版本號 StringDataRightTruncation → 整個 migration 交易 rollback。
#  2) 直接補 telegram_bindings.active_session_id —— /sessions 切換需要此欄位。
#     即使上面 alembic 之後仍失敗，此欄位已在自己的交易中 commit，不會被回滾。
# 兩者皆冪等（IF EXISTS / IF NOT EXISTS），每次啟動安全執行。
echo "[entrypoint] Ensuring critical schema (alembic_version width + telegram active_session_id)..."
python -c "
from core.database import get_connection
conn = get_connection()
try:
    cur = conn.cursor()
    cur.execute(\"ALTER TABLE IF EXISTS alembic_version ALTER COLUMN version_num TYPE VARCHAR(255)\")
    cur.execute(\"ALTER TABLE IF EXISTS telegram_bindings ADD COLUMN IF NOT EXISTS active_session_id TEXT\")
    cur.execute(\"ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS current_session_id TEXT\")
    conn.commit()
    print('[entrypoint] schema ensured: alembic_version=VARCHAR(255); telegram_bindings.active_session_id + users.current_session_id present')
except Exception as exc:
    conn.rollback()
    print('[entrypoint] ensure-schema FAILED:', exc)
finally:
    conn.close()
" || echo "[entrypoint] WARNING: ensure-schema step errored (continuing)." >&2

echo "[entrypoint] Applying database migrations (alembic upgrade head)..."
if alembic upgrade head; then
    echo "[entrypoint] Migrations complete."
else
    echo "[entrypoint] WARNING: alembic upgrade head FAILED (exit $?)." >&2
    echo "[entrypoint] Starting server anyway; check schema/migrations." >&2
fi

echo "[entrypoint] Starting server..."
exec gunicorn -c gunicorn.conf.py api.main:app
