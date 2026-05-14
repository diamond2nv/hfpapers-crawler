#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ─── Config Loading ──────────────────────────────
# hfpapers/config.py

import logging
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"
ENV_PATH = Path(__file__).parent.parent / ".env"

_config_cache: dict | None = None

logger = logging.getLogger("hfpapers.config")

# ─── litellm Price Lookup ───────────────────────
# Uses litellm.model_cost built-in database (2707 models, 109+ providers)
# Source: https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json
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
    """Lookup token price for a model.

    Returns: {input_cost_per_token, output_cost_per_token, litellm_provider, source}
    Unknown models return all zeros.

    Example:
      get_price("deepseek/deepseek-chat")
      # → {input_cost_per_token: 2.8e-07, output_cost_per_token: 4.2e-07, ...}
    """
    cost_map = _get_model_cost()
    info = cost_map.get(model_id, {})
    if not info:
        # Try bare name (without provider prefix)
        bare = model_id.split("/")[-1] if "/" in model_id else model_id
        info = cost_map.get(bare, {})
    return info


def estimate_cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate LLM call cost (USD).

    >>> estimate_cost("deepseek/deepseek-chat", 10000, 500)
    0.00301  # ~0.3 cents
    """
    info = get_price(model_id)
    in_price = info.get("input_cost_per_token", 0.0) or 0.0
    out_price = info.get("output_cost_per_token", 0.0) or 0.0
    return (input_tokens * in_price) + (output_tokens * out_price)


def check_token_budget(estimated_input: int, estimated_output: int,
                       *, model_id: str | None = None) -> bool:
    """Check if token budget is sufficient (general rate limiting, applies to all providers).

    Returns True if within budget, False if exceeded.
    """
    total = estimated_input + estimated_output
    limit = get("budget.max_tokens", 50000)
    if total > limit:
        logger.warning(f"Token budget exceeded: estimated {total:,} > limit {limit:,}")
        return False
    return True


def check_cost_budget(model_id: str, estimated_input: int, estimated_output: int,
                      *, max_cost_usd: float | None = None) -> bool:
    """Check if cost budget is sufficient (only applies to paid providers).

    Local models like Ollama return True (free, no limit).
    Unknown models also return True (assumed free).
    Returns True if within budget, False if exceeded.
    """
    info = get_price(model_id)
    in_price = info.get("input_cost_per_token", 0.0) or 0.0
    out_price = info.get("output_cost_per_token", 0.0) or 0.0

    # Free models (ollama etc.) are not limited
    if in_price == 0.0 and out_price == 0.0:
        return True

    if max_cost_usd is None:
        max_cost_usd = get("budget.max_cost_usd", 0.50)

    cost = (estimated_input * in_price) + (estimated_output * out_price)
    if cost > max_cost_usd:
        logger.warning(
            f"Cost budget exceeded: estimated ${cost:.4f} > limit ${max_cost_usd:.2f} "
            f"(model={model_id})"
        )
        return False
    return True


def check_budget(model_id: str, estimated_input: int, estimated_output: int) -> tuple[bool, str]:
    """Check both token and cost budgets simultaneously.

    Returns: (ok: bool, reason: str)
    - (True, "") means both pass
    - (False, "reason...") indicates which dimension exceeded
    """
    if not check_token_budget(estimated_input, estimated_output):
        return False, "token budget exceeded"
    if not check_cost_budget(model_id, estimated_input, estimated_output):
        return False, "cost budget exceeded"
    return True, ""


# ─── Config Loading ───────────────────────────────


def load_env():
    """Load .env (environment variable override)"""
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH, override=False)
    # Environment variable override
    for key in [
        "DEEPSEEK_API_KEY", "HF_TOKEN", "OLLAMA_API_BASE",
        "LITELLM_PROXY", "LITELLM_API_KEY", "HTTP_PROXY", "HTTPS_PROXY",
    ]:
        val = os.environ.get(key)
        if val:
            os.environ[key] = val


def load_config(reload: bool = False) -> dict:
    """Load YAML config (merged with env)"""
    global _config_cache
    if _config_cache and not reload:
        return _config_cache

    load_env()

    # Test environment variable override
    cfg_path = os.environ.get("_TEST_HFPAPERS_CONFIG") or CONFIG_PATH
    cfg_path = Path(cfg_path)

    # Return default config when config.yaml does not exist
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
                "pdf_dir": "data/pdfs",
                "md_dir": "data/md_extracts",
                "global_dedup": "crawled.json",
            },
            "db": {
                "path": "data/arxiv_meta.db",
            },
        }
        _config_cache = default_cfg
        logger.info("Using default config (no config.yaml)")
        return default_cfg

    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)

    # Inject API keys from .env
    cfg["env"] = {}
    for key in [
        "DEEPSEEK_API_KEY", "HF_TOKEN", "OLLAMA_API_BASE",
        "LITELLM_PROXY", "LITELLM_API_KEY",
    ]:
        cfg["env"][key] = os.environ.get(key, "")

    _config_cache = cfg
    return cfg


def get(key: str, default: Any = None) -> Any:
    """Dot-separated config access: get('search.queries')"""
    cfg = load_config()
    parts = key.split(".")
    v = cfg
    for p in parts:
        if isinstance(v, dict):
            v = v.get(p)
        else:
            return default
    return v if v is not None else default
