"""
User memory system.

Provides persistent agent memory using a nanobot-style two-layer architecture:
- Long-term memory: stores important facts and preferences
- History log: searchable conversation records

Reference: https://github.com/HKUDS/nanobot
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import orjson
from cachetools import TTLCache

from .base import DatabaseBase

logger = logging.getLogger(__name__)

# ── Memory context cache (L1 in-process → L2 Redis → L3 PostgreSQL) ──────────
_MEM_L1: TTLCache = TTLCache(maxsize=512, ttl=30)  # 30 s in-process
_MEM_REDIS_TTL = 120  # 2 min Redis TTL
_MEM_KEY_PREFIX = "mem:"
_FACT_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MAX_EXTRACTED_FACTS_PER_TURN = 3
_MAX_FACT_VALUE_LENGTH = 512

# Track 2: Hermes-style memory quality control.
# Upper bound on the character count of memory (facts + long-term) injected into the
# prompt. When exceeded, truncate by importance (high access_count + recently accessed
# first) to prevent memory from growing unbounded, slowing the prompt, and missing the
# LLM prefix cache. Same rationale as CONTEXT_CHAR_BUDGET (=6000, for history) but
# independent.
MEMORY_CHAR_BUDGET: int = 4000
# Upper bound on the number of facts injected into the prompt (adapted from Mem0:
# keep the most relevant, do not grow unbounded). When exceeded, keep only the top N
# by access_count (hot memories first).
MAX_FACTS_IN_PROMPT: int = 15
# Stale-fact eviction: access_count = 0 (never read into a prompt) AND created more
# than this many days ago → delete. Conservative default of 30 days, to avoid
# deleting recently extracted facts that just have not been queried yet.
STALE_FACT_MAX_AGE_DAYS: int = 30

_mem_redis_client = None
_mem_redis_init = False


def _get_redis_sync():
    global _mem_redis_client, _mem_redis_init
    if _mem_redis_init:
        return _mem_redis_client
    _mem_redis_init = True
    try:
        import redis as _r

        from core.redis_url import resolve_redis_url

        url, _ = resolve_redis_url()
        if not url:
            return None
        client = _r.from_url(
            url, decode_responses=False, socket_connect_timeout=2, socket_timeout=2
        )
        client.ping()
        _mem_redis_client = client
        logger.info("[MemoryCache] Redis connected")
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        logger.warning("[MemoryCache] Redis unavailable: %s", exc)
        _mem_redis_client = None
    return _mem_redis_client


def _mem_cache_key(user_id: str) -> str:
    return _MEM_KEY_PREFIX + user_id


def _mem_l1_get(user_id: str):
    return _MEM_L1.get(_mem_cache_key(user_id))


def _mem_l1_set(user_id: str, data) -> None:
    _MEM_L1[_mem_cache_key(user_id)] = data


def _mem_l1_delete(user_id: str) -> None:
    try:
        del _MEM_L1[_mem_cache_key(user_id)]
    except KeyError:
        pass


def _mem_redis_get(user_id: str):
    r = _get_redis_sync()
    if not r:
        return None
    try:
        raw = r.get(_mem_cache_key(user_id))
        return orjson.loads(raw) if raw else None
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        return None


def _mem_redis_set(user_id: str, data) -> None:
    r = _get_redis_sync()
    if not r:
        return
    try:
        r.setex(_mem_cache_key(user_id), _MEM_REDIS_TTL, orjson.dumps(data))
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        pass


def _mem_redis_delete(user_id: str) -> None:
    r = _get_redis_sync()
    if not r:
        return
    try:
        r.delete(_mem_cache_key(user_id))
    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        pass


def _invalidate_memory_cache(user_id: str) -> None:
    """Invalidate both L1 and L2 cache for a user."""
    _mem_l1_delete(user_id)
    _mem_redis_delete(user_id)


def _apply_memory_budget(context: str, budget: int) -> str:
    """Apply the memory character budget (Track 2).

    ``context`` is assembled by ``_read_from_db``; the blocks are already ordered by
    importance (facts by access_count, long-term is the consolidation summary, history
    is recent). When it exceeds ``budget``, truncate from the tail (i.e., the least
    important part is cut first) and append a truncation marker.

    Conservative design: only trim when clearly over (budget * 1.1 tolerance), to
    avoid frequent trimming that would thrash the cache.
    """
    if not context or len(context) <= budget:
        return context
    # Tolerance: only trim when >10% over budget, to avoid repeated trimming at the boundary
    if len(context) <= int(budget * 1.1):
        return context
    truncated = context[:budget].rsplit("\n", 1)[0]  # cut at a line boundary to avoid splitting a line
    return truncated + "\n\n(Some older memories were omitted to control length)"


def _reset_for_testing() -> None:
    """Reset Redis lazy-init state. For use in tests only."""
    global _mem_redis_client, _mem_redis_init
    _mem_redis_client = None
    _mem_redis_init = False
    _MEM_L1.clear()


def _filter_current_turn_facts(facts: object, turn_index: int) -> list[dict]:
    """Keep only bounded, explicit facts that belong to the current user turn."""
    if not isinstance(facts, list):
        return []

    accepted: list[dict] = []
    for fact in facts:
        if not isinstance(fact, dict):
            continue

        key = fact.get("key")
        value = fact.get("value")
        if not isinstance(key, str) or not isinstance(value, str):
            continue

        key = key.strip()
        value = value.strip()
        if (
            not _FACT_KEY_RE.fullmatch(key)
            or not value
            or len(value) > _MAX_FACT_VALUE_LENGTH
            or fact.get("source_turn") != turn_index
            or fact.get("confidence") != "high"
        ):
            continue

        accepted.append(
            {
                "key": key,
                "value": value,
                "source_turn": turn_index,
                "confidence": "high",
            }
        )
        if len(accepted) == _MAX_EXTRACTED_FACTS_PER_TURN:
            break

    return accepted


# ── Compact session state helpers ─────────────────────────────────────────────
_COMPACT_KEY_PREFIX = "session_compact:"
_COMPACT_REDIS_TTL = 7_200  # 2 hours


def _compact_redis_key(user_id: str, session_id: str) -> str:
    return f"{_COMPACT_KEY_PREFIX}{user_id}:{session_id}"


@dataclass
class CompactedSessionState:
    """Structured compact representation of a session's working state."""

    goal: str
    progress: str
    open_questions: str
    next_steps: str
    turn_index: int
    updated_at: str


class MemoryStore:
    """
    Two-layer memory store.

    Manages the user's long-term memory and conversation history, and supports
    memory consolidation.
    """

    def __init__(
        self,
        user_id: str,
        session_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ):
        """
        Initialize the memory store.

        Args:
            user_id: user ID
            session_id: session ID (optional)
            workspace_id: workspace ID (optional, for multi-tenant isolation)
        """
        self.user_id = user_id
        self.session_id = session_id or "default"
        self.workspace_id = workspace_id
        self._last_consolidated_index: Optional[int] = None

    @property
    def scope(self) -> str:
        """Cache key namespace — user_id, optionally qualified by workspace_id."""
        if self.workspace_id:
            return f"{self.user_id}|workspace:{self.workspace_id}"
        return self.user_id

    # ==================== Long-term memory operations ====================

    def read_long_term(self) -> str:
        """
        Read the user's long-term memory.
        ✅ Cross-session: reads the latest long-term memory (not session-scoped, so
        opening a new conversation does not lose memory).

        Returns:
            The long-term memory content, or an empty string if none exists.
        """
        result = DatabaseBase.query_one(
            """
            SELECT content FROM user_memory
            WHERE user_id = %s AND memory_type = 'long_term'
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (self.user_id,),
        )
        return result["content"] if result else ""

    def write_long_term(self, content: str) -> None:
        """
        Write long-term memory.
        ✅ Uses a fixed session_id='global' to ensure each user has exactly one
        long-term memory record, avoiding the problem of multiple sessions each
        storing their own copy while read_long_term only sees one of them.
        """
        if not content:
            return
        DatabaseBase.execute(
            """
            INSERT INTO user_memory (user_id, session_id, memory_type, content, updated_at)
            VALUES (%s, 'global', 'long_term', %s, NOW())
            ON CONFLICT (user_id, session_id, memory_type)
            DO UPDATE SET content = EXCLUDED.content, updated_at = NOW()
            """,
            (self.user_id, content),
        )
        _invalidate_memory_cache(self.scope)

    # ==================== History log operations ====================

    def append_history(self, entry: str, tools_used: Optional[str] = None) -> None:
        """
        Append a history entry.

        Args:
            entry: the history entry (should start with [YYYY-MM-DD HH:MM])
            tools_used: tools used (optional)
        """
        if not entry or not entry.strip():
            return
        DatabaseBase.execute(
            """
            INSERT INTO user_history_log (user_id, session_id, entry, tools_used)
            VALUES (%s, %s, %s, %s)
            """,
            (self.user_id, self.session_id, entry.rstrip(), tools_used),
        )
        _invalidate_memory_cache(self.scope)

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get history records.
        ✅ Cross-session: returns the user's most recent history across all sessions
        (not session-scoped).

        Args:
            limit: maximum number of records to return

        Returns:
            List of history records (in chronological order).
        """
        results = DatabaseBase.query_all(
            """
            SELECT entry, tools_used, created_at
            FROM user_history_log
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (self.user_id, limit),
        )
        return list(reversed(results)) if results else []

    # ==================== Memory context ====================

    def _read_from_db(
        self,
        include_history: bool = True,
        history_limit: int = 10,
    ) -> str:
        """Actual PostgreSQL read — called only on cache miss.

        Track 2: after assembly, apply the MEMORY_CHAR_BUDGET truncation (hot/recent
        memories first), to prevent memory from growing unbounded.
        """
        parts = []

        # 1. Structured facts (nanoclaw facts) — read_facts already sorts by access_count
        facts_text = self.facts_to_text()
        if facts_text and facts_text != "(no known facts yet)":
            parts.append(f"## Known facts about the user\n{facts_text}")

        # 2. Long-term memory summary (produced by consolidation)
        long_term = self.read_long_term()
        if long_term:
            parts.append(f"## Long-term Memory\n{long_term}")

        if not parts:
            return ""

        context = "\n\n".join(parts)

        # 3. History log
        if include_history:
            history = self.get_history(limit=history_limit)
            if history:
                history_text = "\n\n".join(
                    [h.get("entry", "") for h in history if h.get("entry")]
                )
                if history_text:
                    context += f"\n\n## Recent History\n{history_text}"

        # Track 2: apply the memory character budget (keep hot/recent, truncate the tail)
        return _apply_memory_budget(context, MEMORY_CHAR_BUDGET)

    def get_memory_context(
        self,
        include_history: bool = True,
        history_limit: int = 10,
    ) -> str:
        """
        Get the full memory context (for the LLM prompt) using an L1 → L2 → L3 cache.

        Args:
            include_history: whether to include history records
            history_limit: maximum number of history records

        Returns:
            The formatted memory context string.
        """
        scope = self.scope
        # L1: in-process TTLCache
        cached = _mem_l1_get(scope)
        if cached is not None:
            return cached
        # L2: Redis
        redis_hit = _mem_redis_get(scope)
        if redis_hit is not None:
            _mem_l1_set(scope, redis_hit)
            return redis_hit
        # L3: PostgreSQL
        result = self._read_from_db(include_history, history_limit)
        _mem_l1_set(scope, result)
        _mem_redis_set(scope, result)
        return result

    # ==================== Compact session state ====================

    def read_compact_state(self) -> Optional["CompactedSessionState"]:
        """Read compact session state: Redis → PostgreSQL → None."""
        redis_client = _get_redis_sync()
        key = _compact_redis_key(self.user_id, self.session_id)
        if redis_client:
            try:
                raw = redis_client.get(key)
                if raw:
                    data = orjson.loads(raw)
                    return CompactedSessionState(**data)
            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                pass
        # Fall back to PostgreSQL
        row = DatabaseBase.query_one(
            """SELECT content FROM user_memory
               WHERE user_id = %s AND session_id = %s AND memory_type = 'session_compact'
               ORDER BY updated_at DESC LIMIT 1""",
            (self.user_id, self.session_id),
        )
        if row:
            try:
                data = json.loads(row["content"])
                state = CompactedSessionState(**data)
                # backfill Redis
                if redis_client:
                    try:
                        redis_client.setex(key, _COMPACT_REDIS_TTL, orjson.dumps(data))
                    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                        raise
                    except Exception:
                        pass
                return state
            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                pass
        return None

    def write_compact_state(self, state: "CompactedSessionState") -> None:
        """Persist compact session state to Redis + PostgreSQL."""
        data = {
            "goal": state.goal,
            "progress": state.progress,
            "open_questions": state.open_questions,
            "next_steps": state.next_steps,
            "turn_index": state.turn_index,
            "updated_at": state.updated_at,
        }
        # Write Redis first (fast path)
        redis_client = _get_redis_sync()
        if redis_client:
            try:
                redis_client.setex(
                    _compact_redis_key(self.user_id, self.session_id),
                    _COMPACT_REDIS_TTL,
                    orjson.dumps(data),
                )
            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                logger.debug("[MemoryStore] compact state Redis write failed: %s", exc)
        # Write PostgreSQL (durable)
        DatabaseBase.execute(
            """INSERT INTO user_memory (user_id, session_id, memory_type, content, updated_at)
               VALUES (%s, %s, 'session_compact', %s, NOW())
               ON CONFLICT (user_id, session_id, memory_type)
               DO UPDATE SET content = EXCLUDED.content, updated_at = NOW()""",
            (self.user_id, self.session_id, json.dumps(data)),
        )

    # ==================== Structured facts (nanoclaw extract_memory) ====================

    def read_facts(self) -> dict:
        """
        Read the user's structured facts (key-value pairs).

        Track 2 (Hermes memory quality control):
        - Sort by access_count DESC, last_accessed DESC (hot/recent first)
        - touch: last_accessed=NOW(), access_count+=1 (so hot facts float up)
        - touch failure is silent (does not block reads)

        c014 (proactive memory): preference/holding are sorted first (they most
        affect the angle of the answer), then by access_count/last_accessed. The
        category column is returned for the injection layer to use.

        Returns:
            {key: {value, confidence, source_turn, category}} dict
        """
        results = None
        # Fault tolerance: if the DB has not run the c014 migration (no category
        # column), fall back to a query without category. Avoids a 500 on
        # /api/memory/facts (the user would otherwise see an empty memory panel).
        try:
            results = DatabaseBase.query_all(
                """
                SELECT key, value, confidence, source_turn, category,
                       valid_until, status, verified_at
                FROM user_facts
                WHERE user_id = %s
                  AND (status = 'active' OR status IS NULL)
                  AND (valid_until IS NULL OR valid_until > NOW())
                ORDER BY
                    CASE category
                        WHEN 'preference' THEN 0
                        WHEN 'holding' THEN 1
                        WHEN 'context' THEN 2
                        ELSE 3
                    END,
                    verified_at IS NULL,
                    access_count DESC, last_accessed DESC, updated_at DESC
                """,
                (self.user_id,),
            )
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:  # noqa: BLE001 — missing category column, etc.; fall back
            logger.debug("[MemoryStore] read_facts: category query failed (%s); falling back", exc)
            try:
                results = DatabaseBase.query_all(
                    """
                    SELECT key, value, confidence, source_turn
                    FROM user_facts
                    WHERE user_id = %s
                    ORDER BY access_count DESC, last_accessed DESC, updated_at DESC
                    """,
                    (self.user_id,),
                )
            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                raise
            except Exception:  # noqa: BLE001
                results = None
        # touch: update access counters (background, fault-tolerant)
        # P0-3（2026-08-21）：只 touch 真正會注入 prompt 的前 MAX_FACTS_IN_PROMPT 筆
        # ——原本 WHERE 只有 user_id 全量 +1，被 facts_to_text 截斷掉的冷 facts 也被
        # 加熱，access_count 失真（排序/淘汰都依賴它）→ stale-fact eviction 失效
        if results:
            touched_keys = [r["key"] for r in results[:MAX_FACTS_IN_PROMPT]]
            try:
                DatabaseBase.execute(
                    """
                    UPDATE user_facts
                    SET last_accessed = NOW(), access_count = access_count + 1
                    WHERE user_id = %s AND key = ANY(%s)
                    """,
                    (self.user_id, touched_keys),
                )
            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                raise
            except Exception:  # noqa: BLE001 — touch failure must not block reads
                logger.debug("[MemoryStore] facts touch failed (non-fatal)")
        return {
            r["key"]: {
                "value": r["value"],
                "confidence": r["confidence"],
                "source_turn": r["source_turn"],
                "category": r.get("category", "fact"),
                # c031 治理欄位（Part B UI 需要；fallback 查詢時為 None）
                "valid_until": r.get("valid_until"),
                "status": r.get("status") or "active",
                "verified_at": r.get("verified_at"),
            }
            for r in (results or [])
        }

    def write_facts(self, facts: list) -> None:
        """
        Write structured facts (upsert: new facts are inserted, existing ones updated).

        Args:
            facts: [{'key': str, 'value': str, 'confidence': str, 'source_turn': int,
                     'category': str (optional, defaults to 'fact')}]

        category (added in c014, supports the remember tool's categorized memory):
            - fact: general fact (existing behavior, compatible)
            - preference: investment preference (technical/conservative/crypto-focused); injected into the prompt first
            - holding: holdings (volunteered by the user; the wallet is never auto-scraped)
            - context: conversational context
        """
        if not facts:
            return
        for fact in facts:
            key = fact.get("key", "").strip()
            value = str(fact.get("value", "")).strip()
            if not key or not value:
                continue
            # c031 治理：supersedes 鏈——同 key 覆寫時，舊 row 標 superseded（不刪）
            old_id = self._get_active_fact_id(key)
            if old_id:
                self._supersede_fact(old_id)
            DatabaseBase.execute(
                """
                INSERT INTO user_facts (user_id, key, value, confidence, source_turn,
                                       category, updated_at, source_query,
                                       valid_until, supersedes_id)
                VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s, %s, %s)
                ON CONFLICT (user_id, key)
                DO UPDATE SET
                    value = EXCLUDED.value,
                    confidence = EXCLUDED.confidence,
                    source_turn = EXCLUDED.source_turn,
                    category = EXCLUDED.category,
                    updated_at = NOW(),
                    source_query = EXCLUDED.source_query,
                    valid_until = EXCLUDED.valid_until,
                    supersedes_id = EXCLUDED.supersedes_id,
                    status = 'active'
                """,
                (
                    self.user_id,
                    key,
                    value,
                    fact.get("confidence", "high"),
                    fact.get("source_turn"),
                    fact.get("category", "fact"),
                    fact.get("source_query", ""),
                    self._compute_valid_until(fact),
                    old_id,
                ),
            )
            _invalidate_memory_cache(self.scope)
        # Count control: when over the limit, evict the oldest facts with the lowest access_count (adapted from Mem0)
        self._enforce_fact_limit()

    # ── c031 記憶治理 helpers ────────────────────────────────────────────

    def _get_active_fact_id(self, key: str) -> Optional[int]:
        """取同 key 目前 active 的 row id（供 supersedes 鏈用）。"""
        try:
            rows = DatabaseBase.query_all(
                "SELECT id FROM user_facts "
                "WHERE user_id = %s AND key = %s AND status = 'active' "
                "ORDER BY updated_at DESC LIMIT 1",
                (self.user_id, key),
            )
            return rows[0]["id"] if rows else None
        except Exception:  # noqa: BLE001 — 治理輔助不得阻塞主寫入
            return None

    def _supersede_fact(self, fact_id: int) -> None:
        """把舊事實標 superseded（不刪除，保留審計鏈）。"""
        try:
            DatabaseBase.execute(
                "UPDATE user_facts SET status = 'superseded', "
                "valid_until = NOW() WHERE id = %s",
                (fact_id,),
            )
        except Exception:  # noqa: BLE001
            logger.debug("[MemoryStore] supersede fact %s failed (non-fatal)", fact_id)

    # 時間敏感度 → 有效期（design §3.1）
    _TIME_SENSITIVITY_TTL = {
        "volatile": 1,       # 24 小時——當日觀察、短期訊號
        "dated": 30,         # 30 天——研究結論、目標價、事件假設
    }

    def _compute_valid_until(self, fact: dict) -> Optional[str]:
        """依 time_sensitivity 計算 valid_until（SQL 參數字串或 None=永久）。"""
        sensitivity = str(fact.get("time_sensitivity", "permanent")).lower()
        days = self._TIME_SENSITIVITY_TTL.get(sensitivity)
        if not days:
            return None  # permanent / stable / 未知 → 永久
        try:
            from datetime import datetime, timedelta, timezone

            until = datetime.now(timezone.utc) + timedelta(days=days)
            return until.isoformat()
        except Exception:  # noqa: BLE001
            return None

    def _enforce_fact_limit(self, limit: int = 30) -> None:
        """Fact count cap. When over ``limit``, delete the oldest facts with the lowest access_count.

        Adapted from Mem0: memory does not grow unbounded; keep the most useful.
        limit=30 (DB ceiling; looser than MAX_FACTS_IN_PROMPT=15 to give eviction some buffer).
        """
        try:
            DatabaseBase.execute(
                """
                DELETE FROM user_facts
                WHERE id IN (
                    SELECT id FROM user_facts
                    WHERE user_id = %s
                    ORDER BY access_count ASC, updated_at ASC
                    LIMIT %s
                )
                AND user_id = %s
                AND (SELECT COUNT(*) FROM user_facts WHERE user_id = %s) > %s
                """,
                (self.user_id, 999, self.user_id, self.user_id, limit),
            )
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except Exception:  # noqa: BLE001 — count-control failure must not block
            pass

    def delete_fact(self, key: str) -> bool:
        """Delete a single fact (user-managed memory).

        Returns:
            True if deletion succeeded (including "did not exist"), False on failure.
        """
        try:
            DatabaseBase.execute(
                "DELETE FROM user_facts WHERE user_id = %s AND key = %s",
                (self.user_id, key),
            )
            _invalidate_memory_cache(self.scope)
            return True
        except Exception as exc:
            logger.warning(f"[MemoryStore] delete_fact failed: {exc}")
            return False

    def prune_stale_facts(self, max_age_days: int = STALE_FACT_MAX_AGE_DAYS) -> int:
        """Evict stale facts (Track 2 — Hermes-style memory quality control).

        Deletes facts with access_count=0 (never read into a prompt) AND created more
        than ``max_age_days`` ago. Keeps every fact that has ever been accessed
        (access_count > 0) — those have proven useful.

        Returns the number of deleted rows. Fault-tolerant: returns 0 on failure,
        never raises. Suitable to call periodically after consolidation, or from a
        background task.
        """
        try:
            DatabaseBase.execute(
                """
                DELETE FROM user_facts
                WHERE user_id = %s
                  AND access_count = 0
                  AND created_at < NOW() - (%s || ' days')::INTERVAL
                """,
                (self.user_id, str(max_age_days)),
            )
            # rowcount is available after psycopg2 execute (prepared statements return affected rows)
            # but DatabaseBase.execute does not return rowcount, so here we silently skip the count
            _invalidate_memory_cache(self.scope)
            return -1  # sentinel: executed but no precise count (avoids an extra query)
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:  # noqa: BLE001 — eviction failure must not block the main flow
            logger.debug("[MemoryStore] prune_stale_facts failed (non-fatal): %s", exc)
            return 0

    def facts_to_text(self) -> str:
        """Format structured facts as LLM-readable text.

        Adapted from Mem0: present them as natural-language lines (not a key-value
        list) so the LLM can directly understand and use them. Capped at
        MAX_FACTS_IN_PROMPT (hot ones first).
        """
        facts = self.read_facts()
        if not facts:
            return "(no known facts yet)"
        # Count cap: take only the top N by access_count (read_facts already sorts by hotness)
        items = list(facts.items())[:MAX_FACTS_IN_PROMPT]
        # Natural-language format: the value is itself a full sentence, just list it
        lines = []
        for _key, meta in items:
            lines.append(f"- {meta['value']}")
        return "\n".join(lines)

    async def extract_facts_from_turn(
        self,
        user_message: str,
        assistant_message: str,
        turn_index: int,
        llm: any,
        tools_used: Optional[List[str]] = None,
    ) -> bool:
        """
        Core nanoclaw extract_memory implementation:
        extract structured facts from a single turn and write them to PostgreSQL
        immediately (lightweight, runs each turn — unlike consolidate, which waits
        for accumulation).

        Args:
            user_message: user message
            assistant_message: assistant reply
            turn_index: current turn number
            llm: LangChain LLM instance
            tools_used: list of tools used this turn
        """
        from langchain_core.messages import HumanMessage

        existing_facts = self.facts_to_text()

        prompt = f"""Extract important information about the user from the latest conversation turn, so future responses can be more personalized (adapted from Mem0's natural-language memory).

The user said: {user_message}

Existing memory (avoid duplicates or contradictions; on conflict, the new value overrides):
{existing_facts}
Current turn number: {turn_index}

Reply with JSON containing only the memories added or updated this turn:
{{"facts": [
  {{"key": "investment_style", "value": "The user prefers low-risk blue-chip investments and dislikes high-volatility assets", "source_turn": {turn_index}, "confidence": "high"}}
]}}

Rules:
- Extract ONLY from "The user said"; the assistant reply and tool results must NEVER be a source of user facts.
- **value must be a complete natural-language sentence** (not a single word or tag), so the AI can understand and use it directly when injected into the prompt.
  - ✅ good value: "The user mainly invests in Bitcoin, prefers technical analysis, and dislikes fundamental analysis"
  - ❌ bad value: "bitcoin", "high risk", "prefers blue-chip"
- Keep only information that is "useful for future conversations" (user preferences, investment style, watched assets, risk tolerance, past experience, etc.).
- Do not extract one-off numbers (specific prices, today's news, short-term predictions).
- On conflict, the new value overrides the old (the same key upserts automatically).
- confidence must be "high" (the user said it explicitly); never use inferred or uncertain content.
- If there is no new memory, reply {{"facts": []}}.
- At most 3 memories."""

        try:
            response = llm.invoke([HumanMessage(content=prompt)])
            raw = response.content
            if isinstance(raw, list):
                raw = "".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in raw
                )
            raw = raw.strip()
            json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
            json_str = json_match.group(1).strip() if json_match else raw
            j_start = json_str.find("{")
            j_end = json_str.rfind("}")
            if j_start >= 0 and j_end > j_start:
                json_str = json_str[j_start : j_end + 1]

            # Weak models (e.g., nemotron) often return an empty string or a non-JSON
            # statement ("I cannot..."). This is not an error — it just means no facts
            # were extracted this turn. Silently skip; do not spam the warning log.
            if not json_str or "{" not in json_str:
                logger.debug(
                    "[MemoryStore] extract_facts: LLM returned non-JSON (empty or prose); skipping turn %d",
                    turn_index,
                )
                return True

            result = json.loads(json_str)
            facts = _filter_current_turn_facts(result.get("facts", []), turn_index)

            if facts:
                self.write_facts(facts)
                logger.info(
                    f"[MemoryStore] Extracted {len(facts)} facts at turn {turn_index}"
                )

            return True

        except json.JSONDecodeError as e:
            logger.debug("[MemoryStore] extract_facts JSON parse skipped: %s", e)
            return False
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            # Fact extraction is a non-critical background task. On quota/rate-limit
            # (429) it should not spam ERROR; downgrade to debug and skip quietly.
            # Only other unexpected errors are logged at warning.
            msg = str(e)
            if "429" in msg or "rate limit" in msg.lower() or "quota" in msg.lower():
                logger.debug(
                    "[MemoryStore] extract_facts skipped (rate limited): %s", msg[:120]
                )
            else:
                logger.warning(f"[MemoryStore] extract_facts failed: {e}")
            return False

    # ==================== Consolidation index management ====================

    def get_last_consolidated_index(self) -> int:
        """
        Get the last consolidated index.

        Returns:
            The last consolidated index.

        Bug #8 fix: always read from DB to ensure consistency.
        """
        result = DatabaseBase.query_one(
            """
            SELECT last_consolidated_index FROM user_memory_cache
            WHERE user_id = %s
            """,
            (self.user_id,),
        )
        self._last_consolidated_index = (
            result["last_consolidated_index"] if result else 0
        )
        return self._last_consolidated_index

    def set_last_consolidated_index(self, index: int) -> None:
        """
        Set the last consolidated index.

        Args:
            index: the new index position

        Raises:
            Exception: if the DB write fails

        Bug #4 fix: write to DB first, then update the local copy on success.
        """
        DatabaseBase.execute(
            """
            INSERT INTO user_memory_cache (user_id, session_id, last_consolidated_index, updated_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (user_id)
            DO UPDATE SET
                last_consolidated_index = EXCLUDED.last_consolidated_index,
                session_id = EXCLUDED.session_id,
                updated_at = NOW()
            """,
            (self.user_id, self.session_id, index),
        )
        # Update the local copy only after the DB write succeeds
        self._last_consolidated_index = index

    # ==================== Memory consolidation ====================

    async def consolidate(
        self,
        messages_to_consolidate: List[Dict[str, Any]],
        llm: Any,
    ) -> bool:
        """
        Consolidate conversation history into long-term memory.

        Separation of concerns: the caller is responsible for computing which messages
        to consolidate; this method only performs the consolidation.

        Args:
            messages_to_consolidate: the list of messages to consolidate (slice computed by the caller)
            llm: LangChain LLM instance

        Returns:
            Whether it succeeded.
        """
        if not messages_to_consolidate:
            logger.info("[MemoryStore] No messages to consolidate")
            return True

        logger.info(
            f"[MemoryStore] Consolidating {len(messages_to_consolidate)} messages"
        )

        # Build the conversation text
        lines = []
        for m in messages_to_consolidate:
            content = m.get("content", "")
            if not content:
                continue
            timestamp = m.get("timestamp", "?")[:16] if m.get("timestamp") else "?"
            role = m.get("role", "unknown").upper()
            tools = (
                f" [tools: {', '.join(m.get('tools_used', []))}]"
                if m.get("tools_used")
                else ""
            )
            lines.append(f"[{timestamp}] {role}{tools}: {content}")

        current_memory = self.read_long_term()

        # Build the consolidation prompt
        prompt = f"""Process this conversation and provide a structured memory update.

## Current Long-term Memory
{current_memory or "(empty)"}

## Conversation to Process
{chr(10).join(lines)}

---

Please analyze the conversation and provide:
1. A history entry (2-5 sentences summarizing key events/decisions/topics, starting with [YYYY-MM-DD HH:MM])
2. An updated long-term memory as concise markdown. Include the most useful and
   durable facts (user preferences, recurring topics, investment style). DROP
   one-off details, stale/outdated info, or anything superseded by newer facts
   — keep it focused and under ~500 words so it stays useful long-term.

Respond in this exact JSON format:
{{
    "history_entry": "[2026-01-01 10:00] Summary of what happened...",
    "memory_update": "# Long-term Memory\\n\\n## User Preferences\\n- ...",
    "compact_state": {{
        "goal": "What the user is trying to achieve this session",
        "progress": "What has been resolved or answered",
        "open_questions": "Unresolved questions or threads (empty string if none)",
        "next_steps": "Suggested next actions (empty string if none)"
    }}
}}"""

        try:
            # Call the LLM
            from langchain_core.messages import HumanMessage

            response = llm.invoke([HumanMessage(content=prompt)])
            content = response.content
            if isinstance(content, list):
                content = "".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in content
                )
            content = content.strip()

            # Parse the JSON response
            # Try to extract JSON from a markdown code block
            json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
            if json_match:
                json_str = json_match.group(1).strip()
            else:
                # Try to parse directly
                json_str = content

            # Find the JSON object
            json_start = json_str.find("{")
            json_end = json_str.rfind("}")
            if json_start >= 0 and json_end > json_start:
                json_str = json_str[json_start : json_end + 1]

            result = json.loads(json_str)

            # Save history_entry
            entry = result.get("history_entry")
            if entry:
                if not isinstance(entry, str):
                    entry = json.dumps(entry, ensure_ascii=False)
                self.append_history(entry)

            # Save memory_update
            update = result.get("memory_update")
            if update:
                if not isinstance(update, str):
                    update = json.dumps(update, ensure_ascii=False)
                if update != current_memory:
                    self.write_long_term(update)

            # Save compact session state
            compact_data = result.get("compact_state")
            if compact_data and isinstance(compact_data, dict):
                try:
                    state = CompactedSessionState(
                        goal=str(compact_data.get("goal", "")),
                        progress=str(compact_data.get("progress", "")),
                        open_questions=str(compact_data.get("open_questions", "")),
                        next_steps=str(compact_data.get("next_steps", "")),
                        turn_index=len(messages_to_consolidate),
                        updated_at=datetime.now(timezone.utc).isoformat(),
                    )
                    self.write_compact_state(state)
                except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                    raise
                except Exception as exc:
                    logger.warning("[MemoryStore] compact_state write failed: %s", exc)
            else:
                logger.debug(
                    "[MemoryStore] compact_state absent from LLM consolidation response"
                )

            logger.info(
                f"[MemoryStore] Consolidation done: {len(messages_to_consolidate)} messages"
            )
            # Track 2: opportunistically evict stale facts after consolidation (a natural cleanup point)
            try:
                self.prune_stale_facts()
            except Exception:  # noqa: BLE001 — eviction failure does not affect the consolidation result
                pass
            return True

        except json.JSONDecodeError as e:
            logger.warning(f"[MemoryStore] Failed to parse LLM response as JSON: {e}")
            return False
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            logger.exception(f"[MemoryStore] Consolidation failed: {e}")
            return False


# ==================== Factory function ====================

# Singleton cache
_memory_stores: Dict[str, MemoryStore] = {}


def get_memory_store(
    user_id: str,
    session_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> MemoryStore:
    """
    Get or create a MemoryStore instance.

    Args:
        user_id: user ID
        session_id: session ID (optional)
        workspace_id: workspace ID (optional)

    Returns:
        A MemoryStore instance.
    """
    cache_key = f"{user_id}:{session_id or 'default'}:{workspace_id or ''}"
    if cache_key not in _memory_stores:
        _memory_stores[cache_key] = MemoryStore(user_id, session_id, workspace_id)
    return _memory_stores[cache_key]
