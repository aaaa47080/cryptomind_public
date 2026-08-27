# NVIDIA NIM 測試 Skill

## 用途
使用 NVIDIA NIM endpoint + DeepSeek V4 Pro 模型驗證 CLAW agent 系統完整流程。

## 測試金鑰
```
Provider: nvidia
API Key:  ${NVIDIA_API_KEY}
Endpoint: https://integrate.api.nvidia.com/v1
Model:    deepseek-ai/deepseek-v4-pro
```

## 環境準備

```bash
# 建立乾淨 venv（需 Python 3.13+）
/opt/homebrew/bin/python3.13 -m venv .venv-test
source .venv-test/bin/activate
pip install -r requirements.txt
```

## 測試步驟

### Step 1: API Key 有效性

```bash
source .venv-test/bin/activate
python3 -c "
import json, urllib.request

url = 'https://integrate.api.nvidia.com/v1/chat/completions'
headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer ${NVIDIA_API_KEY}'
}
payload = json.dumps({
    'model': 'deepseek-ai/deepseek-v4-pro',
    'messages': [{'role': 'user', 'content': 'Hello, respond briefly.'}],
    'temperature': 0.5,
    'max_tokens': 1024,
    'stream': False
}).encode()

req = urllib.request.Request(url, data=payload, headers=headers, method='POST')
resp = urllib.request.urlopen(req, timeout=30)
data = json.loads(resp.read())
print(f'✅ Reply: {data[\"choices\"][0][\"message\"][\"content\"][:100]}')
print(f'   Tokens: {data.get(\"usage\",{})}')
"
```

### Step 2: Skill 系統驗證

```bash
source .venv-test/bin/activate
NVIDIA_API_KEY="${NVIDIA_API_KEY}" python3 -W ignore -c "
import warnings; warnings.filterwarnings('ignore')
from dotenv import load_dotenv; load_dotenv()
from core.agents.skill_loader import get_skill_loader

loader = get_skill_loader()
loader.load_all()
skills = loader.list_all()
print(f'✅ {len(skills)} skills loaded')
for s in skills:
    print(f'   {s.name} → {s.applies_to}')

matched = loader.match_skills('BTC 技術面怎麼看', agent_name='crypto')
print(f'\nMatched: {[s.name for s in matched]}')
instructions = loader.get_instructions(matched)
print(f'Instructions: {len(instructions)} chars')
"
```

### Step 3: base_url 傳播驗證（BUG #29 回歸測試）

```bash
source .venv-test/bin/activate
NVIDIA_API_KEY="${NVIDIA_API_KEY}" python3 -W ignore -c "
import warnings; warnings.filterwarnings('ignore')
from dotenv import load_dotenv; load_dotenv()
from utils.llm_client import LLMClientFactory
from core.agents.manager.llm import LLMInvokeMixin

ref = LLMClientFactory.create_client('nvidia', 'deepseek-ai/deepseek-v4-pro')
new = LLMInvokeMixin._create_model_instance('deepseek-ai/deepseek-v4-pro', ref)
base = str(getattr(new, 'openai_api_base', ''))
assert 'nvidia.com' in base, f'base_url LOST: {base}'
print(f'✅ base_url propagated: {base}')
"
```

### Step 4: LLMClientFactory 完整測試

```bash
source .venv-test/bin/activate
NVIDIA_API_KEY="${NVIDIA_API_KEY}" python3 -W ignore -c "
import warnings; warnings.filterwarnings('ignore')
from dotenv import load_dotenv; load_dotenv()
from utils.llm_client import LLMClientFactory
from langchain_core.messages import HumanMessage

client = LLMClientFactory.create_client('nvidia', 'deepseek-ai/deepseek-v4-pro')
print(f'base_url: {getattr(client, \"openai_api_base\", \"?\")}')

resp = client.invoke([HumanMessage(content='BTC 多少錢？一句話。')])
content = resp.content
if isinstance(content, list):
    content = ''.join(p.get('text','') if isinstance(p, dict) else str(p) for p in content)
print(f'✅ Reply: {content[:150]}')
"
```

### Step 5: 完整 CLAW Graph 測試

> 注意：需要覆寫所有 model config 指向同一個 NVIDIA model，否則 model router 會嘗試使用 NVIDIA 上不存在的 model name。

```bash
source .venv-test/bin/activate
NVIDIA_API_KEY="${NVIDIA_API_KEY}" \
timeout 90 python3 -W ignore -c "
import os, asyncio, time, hashlib, re, warnings
warnings.filterwarnings('ignore')
from dotenv import load_dotenv; load_dotenv()

import core.config as core_config
nv = {'provider': 'nvidia', 'model': 'deepseek-ai/deepseek-v4-pro'}
core_config.PRIMARY_MODEL = nv
core_config.BULL_RESEARCHER_MODEL = nv
core_config.BEAR_RESEARCHER_MODEL = nv
core_config.TRADER_MODEL = nv
core_config.SYNTHESIS_MODEL = nv

from utils.llm_client import LLMClientFactory
from core.agents.bootstrap import bootstrap
from core.agents.prompt_registry import PromptRegistry

async def main():
    llm = LLMClientFactory.create_client('nvidia', 'deepseek-ai/deepseek-v4-pro')
    PromptRegistry.load()
    sid = f'claw-{int(time.time())}'
    manager = bootstrap(llm, web_mode=True, language='zh-TW',
                        user_tier='free', user_id='test-claw',
                        session_id=sid, key_fingerprint='abc12345')
    manager._system_prompt = ''
    config = {'configurable': {'thread_id': sid}, 'recursion_limit': 50}

    result = await manager.graph.ainvoke(
        {'query': 'BTC 技術面怎麼看？', 'history': '',
         'history_load_status': 'empty', 'execution_mode': 'vending'}, config)

    tasks = result.get('tasks', [])
    print(f'Tasks: {len(tasks)} | Mode: {result.get(\"execution_mode\",\"?\")}')
    resp = result.get('final_response') or result.get('direct_response_text') or ''
    print(f'Response: {resp[:300]}')

asyncio.run(main())
"
```

## 已知問題

### LangChainPendingDeprecationWarning
```
langgraph/checkpoint/base/__init__.py:17: LangChainPendingDeprecationWarning:
The default value of `allowed_objects` will change in a future version.
```
- 原因：langgraph library 在 import 時觸發，非我們的 code
- `MemorySaver(allowed_objects='core')` 在當前版本不被 `InMemorySaver.__init__` 支援（TypeError）
- 處理：暫時用 `warnings.filterwarnings('ignore')` 抑制，等 langgraph upstream 修正

### Model Routing 404
- Manager 的 model router 嘗試為不同 task type 使用不同 model name
- NVIDIA 只配了一個 model（`deepseek-ai/deepseek-v4-pro`）
- 如果 router 嘗試使用其他 model name → 404
- 解法：在測試時覆寫所有 `core_config.*_MODEL` 指向同一個 NVIDIA model

### `_system_prompt` 屬性
- ManagerAgent 在隔離測試時沒有 `_system_prompt` 屬性
- 需手動設 `manager._system_prompt = ''`
- 正常 server 啟動時不需要（lifespan 初始化會設定）

## 平台設定（前端 UI）

在 Settings 頁面設定：
1. Provider: `nvidia`
2. API Key: `${NVIDIA_API_KEY}`
3. Model: `deepseek-ai/deepseek-v4-pro`
4. 點「測試連線」→ 應回 `valid: true`
5. 儲存 → 在 Chat 問「BTC 技術面怎麼看」→ CLAW 流程啟動

## 相關 Bug 修復

| Bug | 描述 | PR |
|-----|------|-----|
| #29 | `_create_model_instance` 漏掉 base_url | #157 |
