# ─── 配置加载 ──────────────────────────────
# hfpapers/config.py

import os
import logging
import yaml
from pathlib import Path
from dotenv import load_dotenv
from typing import Any

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"
ENV_PATH = Path(__file__).parent.parent / ".env"

_config_cache: dict | None = None

logger = logging.getLogger("hfpapers.config")

# ─── litellm 价格查询 ───────────────────────
# 使用 litellm.model_cost 内置数据库（2707个模型, 109+ provider）
# 来源: https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json
_MODEL_COST_CACHE: dict | None = None


def _get_model_cost() -> dict:
    global _MODEL_COST_CACHE
    if _MODEL_COST_CACHE is not None:
        return _MODEL_COST_CACHE
    try:
        from litellm import model_cost as mc
        _MODEL_COST_CACHE = mc
        return mc
    except Exception:
        _MODEL_COST_CACHE = {}
        return {}


def get_price(model_id: str) -> dict:
    """查询模型的 token 价格。

    返回: {input_cost_per_token, output_cost_per_token, litellm_provider, source}
    未知模型返回全 0。

    示例:
      get_price("deepseek/deepseek-chat")
      # → {input_cost_per_token: 2.8e-07, output_cost_per_token: 4.2e-07, ...}
    """
    cost_map = _get_model_cost()
    info = cost_map.get(model_id, {})
    if not info:
        # 尝试 bare name（无 provider 前缀）
        bare = model_id.split("/")[-1] if "/" in model_id else model_id
        info = cost_map.get(bare, {})
    return info


def estimate_cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """估算 LLM 调用费用（USD）。

    >>> estimate_cost("deepseek/deepseek-chat", 10000, 500)
    0.00301  # ~0.3 美分
    """
    info = get_price(model_id)
    in_price = info.get("input_cost_per_token", 0.0) or 0.0
    out_price = info.get("output_cost_per_token", 0.0) or 0.0
    return (input_tokens * in_price) + (output_tokens * out_price)


def check_token_budget(estimated_input: int, estimated_output: int,
                       *, model_id: str | None = None) -> bool:
    """检查 token 预算是否充足（通用限流，适用于所有 provider）。

    返回 True 表示 budget 内，False 表示超限。
    """
    total = estimated_input + estimated_output
    limit = get("budget.max_tokens", 50000)
    if total > limit:
        logger.warning(f"Token 预算超限: 预计 {total:,} > 上限 {limit:,}")
        return False
    return True


def check_cost_budget(model_id: str, estimated_input: int, estimated_output: int,
                      *, max_cost_usd: float | None = None) -> bool:
    """检查费用预算是否充足（仅对付费 provider 生效）。

    Ollama 等本地模型返回 True（不花钱，不限制）。
    未知模型也返回 True（假设免费）。
    返回 True 表示 budget 内，False 表示超限。
    """
    info = get_price(model_id)
    in_price = info.get("input_cost_per_token", 0.0) or 0.0
    out_price = info.get("output_cost_per_token", 0.0) or 0.0

    # 免费模型（ollama 等）不限制
    if in_price == 0.0 and out_price == 0.0:
        return True

    if max_cost_usd is None:
        max_cost_usd = get("budget.max_cost_usd", 0.50)

    cost = (estimated_input * in_price) + (estimated_output * out_price)
    if cost > max_cost_usd:
        logger.warning(
            f"费用预算超限: 预计 ${cost:.4f} > 上限 ${max_cost_usd:.2f} "
            f"(model={model_id})"
        )
        return False
    return True


def check_budget(model_id: str, estimated_input: int, estimated_output: int) -> tuple[bool, str]:
    """同时检查 token 和费用预算。

    返回: (ok: bool, reason: str)
    - (True, "") 表示双通过
    - (False, "reason...") 表示哪个维度超限
    """
    if not check_token_budget(estimated_input, estimated_output):
        return False, "token 预算超限"
    if not check_cost_budget(model_id, estimated_input, estimated_output):
        return False, "费用预算超限"
    return True, ""


# ─── 配置加载 ───────────────────────────────


def load_env():
    """加载 .env（环境变量覆盖）"""
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH, override=False)
    # 环境变量覆盖
    for key in [
        "DEEPSEEK_API_KEY", "HF_TOKEN", "OLLAMA_API_BASE",
        "LITELLM_PROXY", "LITELLM_API_KEY", "HTTP_PROXY", "HTTPS_PROXY",
    ]:
        val = os.environ.get(key)
        if val:
            os.environ[key] = val


def load_config(reload: bool = False) -> dict:
    """加载 YAML 配置（合并 env）"""
    global _config_cache
    if _config_cache and not reload:
        return _config_cache

    load_env()

    # 测试环境变量覆盖
    cfg_path = os.environ.get("_TEST_HFPAPERS_CONFIG") or CONFIG_PATH
    cfg_path = Path(cfg_path)

    # config.yaml 不存在时返回默认配置
    if not cfg_path.exists():
        default_cfg = {
            "search": {
                "max_per_dim": 50,
                "queries": [
                    {"query": "neural operator", "category": "neural-operator", "priority": 1},
                ],
            },
            "keywords": {
                "include_high": ["neural operator", "pde"],
                "exclude": ["quantum", "llm"],
            },
            "classification": {
                "threshold_pass": 30,
                "title_similarity_min": 0.40,
            },
            "paths": {
                "data_dir": "data",
                "pdf_dir": "pdfs",
                "md_dir": "mds",
                "global_dedup": "crawled.json",
            },
            "db": {
                "path": "data/arxiv_meta.db",
            },
        }
        _config_cache = default_cfg
        logger.info("使用默认配置（无 config.yaml）")
        return default_cfg

    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)

    # .env 中的 API key 注入
    cfg["env"] = {}
    for key in [
        "DEEPSEEK_API_KEY", "HF_TOKEN", "OLLAMA_API_BASE",
        "LITELLM_PROXY", "LITELLM_API_KEY",
    ]:
        cfg["env"][key] = os.environ.get(key, "")

    _config_cache = cfg
    return cfg


def get(key: str, default: Any = None) -> Any:
    """点号分隔的配置访问: get('search.queries')"""
    cfg = load_config()
    parts = key.split(".")
    v = cfg
    for p in parts:
        if isinstance(v, dict):
            v = v.get(p)
        else:
            return default
    return v if v is not None else default
