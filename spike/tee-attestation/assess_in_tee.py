"""TEE 內執行的風險評估入口（spike）。

在 TEE（Phala Cloud）內跑：讀入一份 Omniston quote，用
cryptomind-safety-kernel（開源審查核心）算出風險等級與同意要求，
輸出可驗證的 report。

設計原則：
  - 只做純規則計算（safety_kernel 無網路 I/O）——不碰金流、不碰私鑰。
  - report 內含 kernel 版本 + 輸入/輸出 hash——外部可重算驗證
    （attestation 由 TEE 平台提供，證明「這段計算真的發生在可信硬體」）。

用法（TEE 內 / 本機模擬）：
  python assess_in_tee.py sample_quote.json > report.json
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

# spike 目錄不在套件路徑上——把 repo root 加進來才能 import safety_kernel。
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from safety_kernel import __version__ as KERNEL_VERSION
from safety_kernel.consent_gate import requires_consent
from safety_kernel.risk_tiers import assess_risk

# report schema 版本（與外部驗證工具對照）。
REPORT_SCHEMA = "tee-assess.v1"


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def assess_quote(quote: dict) -> dict:
    """用 kernel 規則評估一份 quote，回傳結構化報告（純函式，可離線驗證）。"""
    price_impact_pct = float(quote.get("price_impact_percent", 0))
    risk = assess_risk(price_impact_pct, None)

    # 同意事實（與主平台 consent_gate 相同語意）：換什麼、換多少、
    # 最低收到、風險等級、價格影響、kernel 版本。
    facts = {
        "input_asset": quote.get("input_asset", ""),
        "output_asset": quote.get("output_asset", ""),
        "input_units": str(quote.get("input_units", "")),
        "min_output_amount": str(quote.get("min_output_amount", "")),
        "price_impact_percent": price_impact_pct,
        "risk_level": risk.level,
        "kernel_version": KERNEL_VERSION,
    }
    canonical = json.dumps(facts, sort_keys=True, separators=(",", ":"))

    return {
        "schema": REPORT_SCHEMA,
        "kernel_version": KERNEL_VERSION,
        "input_hash": _sha256_hex(json.dumps(quote, sort_keys=True)),
        "facts_hash": _sha256_hex(canonical),
        "result": {
            "risk_level": risk.level,
            "needs_consent": requires_consent(risk.level),
            "blocked": risk.blocked,
            "reasons": risk.reasons,
        },
    }


def main() -> int:
    if len(sys.argv) != 2:
        print("用法：python assess_in_tee.py <quote.json>", file=sys.stderr)
        return 2
    quote = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(json.dumps(assess_quote(quote), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
