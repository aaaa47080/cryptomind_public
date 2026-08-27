#!/bin/bash
# ============================================================
# Claude Code 工具一鍵安裝腳本
# 安裝：CodeGraph + agent-skills + 升級 Claude Code CLI
# 使用方式：bash setup_claude_tools.sh
# ============================================================

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo -e "${BLUE}======================================${NC}"
echo -e "${BLUE}  Claude Code 工具安裝腳本${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""

# ── 1. 升級 Claude Code CLI ──────────────────────────────
echo -e "${YELLOW}[1/4] 升級 Claude Code CLI...${NC}"
if command -v claude &>/dev/null; then
    CURRENT=$(claude --version 2>/dev/null | head -1)
    echo "      目前版本：$CURRENT"
fi
npm install -g @anthropic-ai/claude-code 2>&1 | grep -E "(added|updated|error)" || true
echo -e "${GREEN}      ✓ Claude Code CLI 升級完成${NC}"
echo ""

# ── 2. 安裝 CodeGraph ────────────────────────────────────
echo -e "${YELLOW}[2/4] 安裝 CodeGraph...${NC}"
npm install -g @colbymchenry/codegraph
echo -e "${GREEN}      ✓ CodeGraph 安裝完成 ($(codegraph --version))${NC}"
echo ""

# ── 3. 設定 CodeGraph MCP（寫入 ~/.claude.json）──────────
echo -e "${YELLOW}[3/4] 設定 CodeGraph MCP...${NC}"
CLAUDE_JSON="$HOME/.claude.json"

if [ ! -f "$CLAUDE_JSON" ]; then
    echo '{}' > "$CLAUDE_JSON"
fi

# 用 node 安全合併 JSON，不破壞現有設定
node -e "
const fs = require('fs');
const path = '$CLAUDE_JSON';
let config = {};
try { config = JSON.parse(fs.readFileSync(path, 'utf8')); } catch(e) {}
if (!config.mcpServers) config.mcpServers = {};
config.mcpServers.codegraph = {
  type: 'stdio',
  command: 'codegraph',
  args: ['serve', '--mcp']
};
fs.writeFileSync(path, JSON.stringify(config, null, 2));
console.log('      ~/.claude.json 已更新');
"

# 設定 auto-allow permissions
SETTINGS_DIR="$HOME/.claude"
SETTINGS_FILE="$SETTINGS_DIR/settings.json"
mkdir -p "$SETTINGS_DIR"

node -e "
const fs = require('fs');
const path = '$SETTINGS_FILE';
let config = {};
try { config = JSON.parse(fs.readFileSync(path, 'utf8')); } catch(e) {}
if (!config.permissions) config.permissions = {};
if (!config.permissions.allow) config.permissions.allow = [];
const tools = [
  'mcp__codegraph__codegraph_search',
  'mcp__codegraph__codegraph_context',
  'mcp__codegraph__codegraph_callers',
  'mcp__codegraph__codegraph_callees',
  'mcp__codegraph__codegraph_impact',
  'mcp__codegraph__codegraph_node',
  'mcp__codegraph__codegraph_status',
  'mcp__codegraph__codegraph_files',
  'mcp__codegraph__codegraph_explore'
];
tools.forEach(t => {
  if (!config.permissions.allow.includes(t)) config.permissions.allow.push(t);
});
fs.writeFileSync(path, JSON.stringify(config, null, 2));
console.log('      ~/.claude/settings.json 已更新（auto-allow 已設定）');
"

echo -e "${GREEN}      ✓ CodeGraph MCP 設定完成${NC}"
echo ""

# ── 4. 初始化 CodeGraph（當前專案）──────────────────────
echo -e "${YELLOW}[4/4] 初始化 CodeGraph 專案索引...${NC}"
echo "      專案路徑：$PROJECT_DIR"
cd "$PROJECT_DIR"
codegraph init --index
echo -e "${GREEN}      ✓ 專案索引建立完成${NC}"
echo ""

# ── 完成提示 ─────────────────────────────────────────────
echo -e "${BLUE}======================================${NC}"
echo -e "${GREEN}  所有安裝完成！${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""
echo "  後續步驟："
echo ""
echo -e "  ${YELLOW}agent-skills 安裝（在 Claude Code CLI 裡執行）：${NC}"
echo "  1. 重新啟動 Claude Code"
echo "  2. 輸入："
echo "     /plugin marketplace add addyosmani/agent-skills"
echo "     /plugin install agent-skills@addy-agent-skills"
echo ""
echo -e "  ${YELLOW}CodeGraph 使用：${NC}"
echo "  - 重新啟動 Claude Code 後 MCP 自動連線"
echo "  - 新專案用：codegraph init -i"
echo "  - 查狀態：codegraph status"
echo ""
echo -e "${GREEN}  完成！重新啟動 Claude Code 讓設定生效。${NC}"
echo ""
