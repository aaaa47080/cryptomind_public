"""
模型配置文件 - 統一管理所有 LLM 模型配置

在此修改模型名稱，全系統自動同步（後端 + 前端）。
"""

# ============================================================================
# 具名常數 —— 在此修改即可全系統生效
# ============================================================================

OPENAI_DEFAULT_MODEL = "gpt-5.4-mini"  # OpenAI 預設模型（快速/一般分析）
OPENAI_PRO_MODEL = "gpt-5.4"  # OpenAI 進階模型（深度分析）
OPENAI_FRONTIER_MODEL = "gpt-5.5"  # OpenAI 最先進模型（旗艦）
OPENAI_LEGACY_MODEL = "gpt-4.1-mini"  # OpenAI 舊版相容模型（保留以便切換）
GEMINI_DEFAULT_MODEL = "gemini-3.5-flash"  # Google Gemini 預設模型（快速，GA）
GEMINI_PRO_MODEL = "gemini-2.5-pro"  # Google Gemini 進階模型（穩定）
DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-flash"  # DeepSeek V4 Flash（快速）
DEEPSEEK_PRO_MODEL = "deepseek-v4-pro"  # DeepSeek V4 Pro（深度）

# ============================================================================
# Provider 註冊表（單一真實來源 / Single Source of Truth）
#
# 後端建立 client、驗證 key，以及前端下拉，全部讀這張表。
# 要新增一個 provider：在 PROVIDER_REGISTRY 加一行 + 在 MODEL_CONFIG 補模型清單即可，
# 路由（create_client / validate_key / _get_api_key / 前端下拉）會自動生效。
#
# 欄位說明：
#   lc_provider   — LangChain init_chat_model 的 model_provider 值
#                   ("openai" / "google_genai" / "anthropic")
#   base_url      — OpenAI 相容端點網址；官方 SDK（openai/gemini/anthropic）留 None
#   api_key_envs  — 從環境變數讀 server key 時的候選名稱（依序 fallback）
#
# NVIDIA / MiniMax / DeepSeek / Kimi / 通義 / GLM / 豆包 等都提供 OpenAI 相容端點，
# 因此共用 lc_provider="openai" + base_url 即可，無需各自的 SDK 套件。
# ============================================================================

PROVIDER_REGISTRY: dict[str, dict] = {
    "openai": {
        "lc_provider": "openai",
        "base_url": None,
        "api_key_envs": ["OPENAI_API_KEY"],
    },
    # openai_server：只吃 SERVER_OPENAI_API_KEY，不 fallback 到 OPENAI_API_KEY，
    # 避免干擾 BYOK 模式。
    "openai_server": {
        "lc_provider": "openai",
        "base_url": None,
        "api_key_envs": ["SERVER_OPENAI_API_KEY"],
    },
    "google_gemini": {
        "lc_provider": "google_genai",
        "base_url": None,
        "api_key_envs": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
    },
    "anthropic": {
        "lc_provider": "anthropic",
        "base_url": None,
        "api_key_envs": ["ANTHROPIC_API_KEY"],
    },
    "openrouter": {
        "lc_provider": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_envs": ["OPENROUTER_API_KEY"],
    },
    "deepseek": {
        "lc_provider": "openai",
        "base_url": "https://api.deepseek.com",
        "api_key_envs": ["DEEPSEEK_API_KEY"],
    },
    "siliconflow": {
        "lc_provider": "openai",
        "base_url": "https://api.siliconflow.cn/v1",
        "api_key_envs": ["SILICONFLOW_API_KEY"],
    },
    "groq": {
        "lc_provider": "openai",
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_envs": ["GROQ_API_KEY"],
    },
    "moonshot": {
        "lc_provider": "openai",
        "base_url": "https://api.moonshot.cn/v1",
        "api_key_envs": ["MOONSHOT_API_KEY"],
    },
    "dashscope": {
        "lc_provider": "openai",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key_envs": ["DASHSCOPE_API_KEY"],
    },
    "zhipu": {
        "lc_provider": "openai",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key_envs": ["ZHIPU_API_KEY"],
    },
    "minimax": {
        "lc_provider": "openai",
        "base_url": "https://api.minimax.io/v1",
        "api_key_envs": ["MINIMAX_API_KEY"],
    },
    "volcengine": {
        "lc_provider": "openai",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "api_key_envs": ["VOLCENGINE_API_KEY", "ARK_API_KEY"],
    },
    "nvidia": {
        "lc_provider": "openai",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "api_key_envs": ["NVIDIA_API_KEY"],
    },
}

# OpenAI-compatible providers 的 base_url 對照表（從註冊表自動衍生，保留向後相容）。
# 既有程式（user_client_factory）以此判斷是否為 OpenAI 相容 provider。
OPENAI_COMPATIBLE_BASE_URLS: dict[str, str] = {
    name: cfg["base_url"]
    for name, cfg in PROVIDER_REGISTRY.items()
    if cfg["lc_provider"] == "openai" and cfg["base_url"]
}

# ============================================================================
# 前端模型清單（供 /api/model-config 端點使用）
#
# free_input=True 的 provider 在前端改用文字輸入框，讓用戶自填任意模型名
# （適合模型眾多/更新快的聚合平台，如 OpenRouter / NVIDIA / 火山方舟）。
# ============================================================================

MODEL_CONFIG = {
    "openai": {
        "display": "OpenAI",
        "default_model": OPENAI_DEFAULT_MODEL,
        "available_models": [
            {"value": OPENAI_FRONTIER_MODEL, "display": "GPT-5.5 (旗艦)"},
            {"value": OPENAI_PRO_MODEL, "display": "GPT-5.4 (進階)"},
            {"value": OPENAI_DEFAULT_MODEL, "display": "GPT-5.4 Mini (快速)"},
            {"value": "gpt-5.4-nano", "display": "GPT-5.4 Nano (超快)"},
            {"value": "gpt-5-mini", "display": "GPT-5 Mini"},
            {"value": OPENAI_LEGACY_MODEL, "display": "GPT-4.1 Mini (舊版)"},
        ],
    },
    "google_gemini": {
        "display": "Google Gemini",
        "default_model": GEMINI_DEFAULT_MODEL,
        "available_models": [
            {"value": GEMINI_DEFAULT_MODEL, "display": "Gemini 3.5 Flash (快速)"},
            {"value": "gemini-3.1-pro-preview", "display": "Gemini 3.1 Pro (進階)"},
            {"value": "gemini-3-flash-preview", "display": "Gemini 3 Flash (預覽)"},
            {"value": GEMINI_PRO_MODEL, "display": "Gemini 2.5 Pro (穩定)"},
        ],
    },
    "anthropic": {
        "display": "Anthropic Claude",
        "default_model": "claude-sonnet-4-6",
        "available_models": [
            {"value": "claude-fable-5", "display": "Claude Fable 5 (最強)"},
            {"value": "claude-opus-4-8", "display": "Claude Opus 4.8 (旗艦)"},
            {"value": "claude-opus-4-7", "display": "Claude Opus 4.7"},
            {"value": "claude-sonnet-4-6", "display": "Claude Sonnet 4.6 (均衡)"},
            {"value": "claude-haiku-4-5", "display": "Claude Haiku 4.5 (快速)"},
        ],
    },
    "groq": {
        "display": "Groq",
        "default_model": "openai/gpt-oss-120b",
        "available_models": [
            {"value": "openai/gpt-oss-120b", "display": "GPT-OSS 120B"},
            {"value": "openai/gpt-oss-20b", "display": "GPT-OSS 20B (快速)"},
            {"value": "llama-3.3-70b-versatile", "display": "Llama 3.3 70B"},
            {
                "value": "meta-llama/llama-4-scout-17b-16e-instruct",
                "display": "Llama 4 Scout 17B",
            },
            {"value": "qwen/qwen3-32b", "display": "Qwen3 32B"},
            {"value": "llama-3.1-8b-instant", "display": "Llama 3.1 8B (超快)"},
        ],
    },
    "openrouter": {
        "display": "OpenRouter",
        "default_model": OPENAI_DEFAULT_MODEL,
        "free_input": True,  # OpenRouter 有太多模型，讓用戶自行輸入
        "available_models": [],
    },
    "deepseek": {
        "display": "DeepSeek",
        "default_model": DEEPSEEK_DEFAULT_MODEL,
        "available_models": [
            {"value": DEEPSEEK_PRO_MODEL, "display": "DeepSeek V4 Pro (深度)"},
            {"value": DEEPSEEK_DEFAULT_MODEL, "display": "DeepSeek V4 Flash (快速)"},
        ],
    },
    "siliconflow": {
        "display": "SiliconFlow 矽基流動",
        "default_model": "deepseek-ai/DeepSeek-V3.2",
        "available_models": [
            {"value": "deepseek-ai/DeepSeek-V3.2", "display": "DeepSeek V3.2"},
            {
                "value": "Qwen/Qwen3-235B-A22B-Thinking-2507",
                "display": "Qwen3 235B Thinking",
            },
            {
                "value": "Qwen/Qwen3-235B-A22B-Instruct-2507",
                "display": "Qwen3 235B Instruct",
            },
            {"value": "THUDM/glm-5.1", "display": "GLM-5.1"},
        ],
    },
    "moonshot": {
        "display": "Kimi (Moonshot)",
        "default_model": "kimi-k2.6",
        "available_models": [
            {"value": "kimi-k2.6", "display": "Kimi K2.6"},
            {"value": "kimi-k2.5", "display": "Kimi K2.5"},
        ],
    },
    "dashscope": {
        "display": "通義千問 DashScope",
        "default_model": "qwen3.6-plus",
        "available_models": [
            {"value": "qwen3.6-plus", "display": "Qwen3.6 Plus (深度)"},
            {"value": "qwen3.6-flash", "display": "Qwen3.6 Flash (快速)"},
        ],
    },
    "zhipu": {
        "display": "智譜 GLM",
        "default_model": "glm-5.1",
        "available_models": [
            {"value": "glm-5.1", "display": "GLM-5.1"},
            {"value": "glm-4.7-flash", "display": "GLM-4.7 Flash (快速)"},
        ],
    },
    "minimax": {
        "display": "MiniMax",
        "default_model": "MiniMax-M2.7",
        "available_models": [
            {"value": "MiniMax-M2.7", "display": "MiniMax M2.7"},
            {"value": "MiniMax-M2.7-highspeed", "display": "MiniMax M2.7 高速"},
        ],
    },
    "volcengine": {
        "display": "火山方舟 / 豆包",
        "default_model": "doubao-seed-1-6-251015",
        "free_input": True,  # 豆包 endpoint/模型 ID 因開通地域而異，自行輸入較穩
        "available_models": [],
    },
    "nvidia": {
        "display": "NVIDIA NIM",
        "default_model": "minimaxai/minimax-m3",
        "free_input": True,  # NVIDIA NIM 模型眾多，讓用戶自行輸入
        "available_models": [],
    },
}


def get_provider_runtime(provider: str) -> dict | None:
    """
    取得 provider 的執行期路由設定（lc_provider / base_url / api_key_envs）。

    這是所有後端 factory 的路由依據——拿不到（回 None）代表不支援該 provider。
    """
    return PROVIDER_REGISTRY.get(provider)


def resolve_server_api_key(provider: str) -> str:
    """
    依註冊表的 api_key_envs，從環境變數依序解析 server 端 API key。

    Returns:
        str: 找到的第一個非空 key，否則空字串。
    """
    import os

    runtime = PROVIDER_REGISTRY.get(provider)
    if not runtime:
        return ""
    for env_name in runtime.get("api_key_envs", []):
        value = os.getenv(env_name)
        if value:
            return value
    return ""


def is_free_input_provider(provider: str) -> bool:
    """該 provider 是否讓用戶自由輸入模型名（前端用文字框而非下拉）。"""
    return bool(MODEL_CONFIG.get(provider, {}).get("free_input", False))


def get_available_models(provider: str) -> list[dict[str, str]]:
    """
    獲取指定提供商的可用模型列表

    Args:
        provider (str): 提供商名稱

    Returns:
        list: 模型配置列表，每個項目包含 'value' 和 'display' 鍵性
    """
    return MODEL_CONFIG.get(provider, {}).get("available_models", [])


def get_default_model(provider: str) -> str:
    """
    獲取指定提供商的默認模型

    Args:
        provider (str): 提供商名稱

    Returns:
        str: 默認模型名稱
    """
    return MODEL_CONFIG.get(provider, {}).get("default_model", OPENAI_DEFAULT_MODEL)


def get_all_providers():
    """
    獲取所有支持的提供商列表

    Returns:
        list: 支持的提供商名稱列表
    """
    return list(MODEL_CONFIG.keys())


def is_valid_model(provider, model_name):
    """
    檢查指定提供商是否支持特定模型

    Args:
        provider (str): 提供商名稱
        model_name (str): 模型名稱

    Returns:
        bool: 模型是否有效
    """
    available_models = get_available_models(provider)
    return any(model["value"] == model_name for model in available_models)


def get_model_display_name(provider, model_value):
    """
    獲取模型的顯示名稱

    Args:
        provider (str): 提供商名稱
        model_value (str): 模型值

    Returns:
        str: 模型的顯示名稱，如果找不到則返回模型值本身
    """
    available_models = get_available_models(provider)
    for model in available_models:
        if model["value"] == model_value:
            return model["display"]
    return model_value  # 如果找不到顯示名稱，返回模型值本身
