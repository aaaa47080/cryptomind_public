#!/usr/bin/env python3
"""Scan JS/HTML for hardcoded Chinese text that bypasses the i18n system.

Excludes legitimate Chinese usage:
  - i18n JSON locale files (web/js/i18n/*.json)
  - Comments (// /* */ and HTML <!-- -->)
  - console.{log,warn,error,info,debug} statements
  - Signal matching: .includes('突破'), .indexOf('賣出'), .match(...)
  - Regex patterns containing Chinese ranges
  - JSDoc tags (@param, @returns)

Flags: any string literal or HTML text content containing Chinese characters
that should be routed through window.I18n.t() or data-i18n attribute.

Exit code 0 = clean, 1 = hardcoded Chinese found (CI gate).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")

# Line-level exclusion patterns. If a line matches ANY of these, it is skipped.
EXCLUDE_PATTERNS = [
    re.compile(r"^\s*//"),  # JS line comment
    re.compile(r"^\s*/\*"),  # JS block comment open
    re.compile(r"^\s*\*"),  # JS block comment body
    re.compile(r"^\s*<!--"),  # HTML comment
    re.compile(r"^\s*\*/"),  # JS block comment close
    re.compile(r"console\.(log|warn|error|info|debug|trace)\s*\("),
    re.compile(r"\.includes\s*\(\s*['\"][^'\"]*[\u4e00-\u9fff]"),  # signal match
    re.compile(r"\.indexOf\s*\(\s*['\"][^'\"]*[\u4e00-\u9fff]"),  # signal match
    re.compile(r"\.startsWith\s*\(\s*['\"][^'\"]*[\u4e00-\u9fff]"),
    re.compile(r"\.endsWith\s*\(\s*['\"][^'\"]*[\u4e00-\u9fff]"),
    re.compile(r"\.match\s*\(\s*[/']"),  # regex match
    re.compile(r"\.test\s*\(\s*"),  # regex test
    re.compile(r"^\s*#\s*(region|endregion|pragma)"),  # region markers
    re.compile(r"@(param|returns?|type|example|throws?|deprecated|see)"),
    re.compile(r"'\\u[0-9a-fA-F]{4}'"),  # unicode escape literals
    re.compile(r'"\.\.\."|\u2026'),  # ellipsis as separator
    re.compile(r"^\s*/\*[\s\S]*?\*/\s*$"),  # inline JS block comment /* ... */
]

# Files to skip entirely (by relative path suffix)
SKIP_PATHS = {
    "web/js/i18n/en.json",
    "web/js/i18n/zh-TW.json",
}

# Directories to skip
SKIP_DIRS = {"node_modules", "vendor", "dist", ".vite", "__pycache__"}

# Files to skip entirely (by filename pattern, checked after directory skip)
SKIP_FILE_PATTERNS = [
    "web/js/twstock.js",  # stock data: Chinese company names are data, not UI strings
    "web/js/hkstock.js",  # stock data: Chinese company names
    "web/js/commodity.js",  # commodity data: Chinese commodity names
    "web/js/notification-service.js",  # demo notification templates (development fixture)
]


def should_skip_path(path: Path) -> bool:
    rel = str(path.relative_to(ROOT)).replace("\\", "/")
    if rel in SKIP_PATHS:
        return True
    if any(part in SKIP_DIRS for part in path.parts):
        return True
    if "i18n" in path.parts and path.suffix == ".json":
        return True
    if any(pattern in rel for pattern in SKIP_FILE_PATTERNS):
        return True
    return False


def strip_comments(line: str) -> str:
    """Remove JS/HTML comments from line so Chinese inside comments isn't flagged."""
    # Remove inline /* ... */ block comments
    line = re.sub(r"/\*.*?\*/", "", line)
    # Remove trailing // comments (but not URI schemes)
    if "://" not in line:
        line = re.sub(r"//.*$", "", line)
    # Remove HTML comments
    line = re.sub(r"<!--.*?-->", "", line)
    return line


def should_exclude_line(line: str) -> bool:
    stripped = strip_comments(line)
    # If no Chinese remains after stripping comments, skip
    if not CHINESE_RE.search(stripped):
        return True
    return any(p.search(stripped) for p in EXCLUDE_PATTERNS)


def iter_target_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in {".js", ".html", ".mjs"}:
            continue
        if should_skip_path(path):
            continue
        yield path


def scan_file(path: Path) -> list[tuple[int, str]]:
    """Return list of (line_number, line_content) with flagged Chinese."""
    issues: list[tuple[int, str]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return issues

    in_block_comment = False
    for i, raw_line in enumerate(text.split("\n"), 1):
        line = raw_line.rstrip()

        # Track JS block comments /* ... */ across lines
        if "/*" in line and "*/" not in line:
            in_block_comment = True
            continue
        if in_block_comment:
            if "*/" in line:
                in_block_comment = False
            continue

        if not CHINESE_RE.search(line):
            continue
        if should_exclude_line(line):
            continue

        issues.append((i, line.strip()[:240]))
    return issues


def main() -> int:
    total_issues = 0
    files_with_issues = 0
    by_file: list[tuple[Path, int]] = []

    for path in iter_target_files(WEB_DIR):
        issues = scan_file(path)
        if not issues:
            continue
        files_with_issues += 1
        rel = path.relative_to(ROOT)
        by_file.append((rel, len(issues)))
        for line_no, content in issues:
            print(f"{rel}:{line_no}: {content}")
            total_issues += 1

    print()
    print(f"files_with_hardcoded_chinese={files_with_issues}")
    print(f"total_hardcoded_chinese_lines={total_issues}")

    if files_with_issues > 0:
        print()
        print("Top files by issue count:")
        for rel, count in sorted(by_file, key=lambda x: -x[1])[:10]:
            print(f"  {count:4d}  {rel}")

    return 1 if total_issues > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
