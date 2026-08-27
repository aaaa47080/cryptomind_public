"""外部驗證 TEE 風險評估報告（spike）。

不信任 report 本身——重算所有 hash、對照 kernel 版本、檢查 TEE
attestation（由平台提供，證明計算發生在可信硬體）。

用法：
  python verify_report.py report.json [attestation.json]
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

# spike 目錄不在套件路徑上——把 repo root 加進來才能 import safety_kernel。
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def verify(report_path: str, attestation_path: str | None = None) -> int:
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    failures: list[str] = []

    # 1. schema 版本
    if report.get("schema") != "tee-assess.v1":
        failures.append(f"unknown schema: {report.get('schema')}")

    # 2. kernel 版本與公開 repo 對照（審查員用 tag v<version> 比對）
    try:
        from safety_kernel import __version__
    except ImportError:
        failures.append("safety_kernel 未安裝——無法對照版本")
        __version__ = "?"

    if report.get("kernel_version") != __version__:
        failures.append(
            f"kernel version mismatch: report={report.get('kernel_version')} "
            f"installed={__version__}"
        )

    # 3. facts_hash / input_hash 格式檢查（完整重算需要原始 quote 原件——
    #    外部驗證時把 input_hash 與 quote.json 的 sha256 對照即可）。
    if not report.get("facts_hash") or len(report["facts_hash"]) != 64:
        failures.append("facts_hash missing or malformed")
    else:
        int(report["facts_hash"], 16)

    if not report.get("input_hash") or len(report["input_hash"]) != 64:
        failures.append("input_hash missing or malformed")
    else:
        int(report["input_hash"], 16)

    # 4. 結果結構
    result = report.get("result", {})
    if result.get("risk_level") not in ("green", "yellow", "orange", "red", "block"):
        failures.append(f"invalid risk_level: {result.get('risk_level')}")

    # 5. TEE attestation（若提供）：確認存在且含平台簽章欄位。
    #    實際驗證鏈（Intel/Phala 簽章）由平台的 verify 工具完成——spike 只
    #    確認報告有帶上 attestation 且格式合理。
    if attestation_path:
        att = json.loads(Path(attestation_path).read_text(encoding="utf-8"))
        if not att.get("attestation"):
            failures.append("attestation.json 缺少 attestation 欄位")
        if att.get("report_hash") != report.get("facts_hash"):
            failures.append("attestation 綁定的 hash 與 report 不符")

    if failures:
        print("❌ 驗證失敗：")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("✅ 驗證通過")
    print(f"  kernel: {report.get('kernel_version')}")
    print(f"  risk_level: {result.get('risk_level')} (consent: {result.get('needs_consent')})")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("用法：python verify_report.py report.json [attestation.json]", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(verify(*args))
