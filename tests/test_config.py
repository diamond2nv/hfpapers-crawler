#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test config module — YAML loading + env merging + budget checking"""
import os
import tempfile

from hfpapers.config import check_cost_budget, check_token_budget, estimate_cost, get, load_config


class TestConfigLoad:
    def test_load_config_returns_dict(self, test_env):
        cfg = load_config(reload=True)
        assert isinstance(cfg, dict)
        assert "search" in cfg
        assert "keywords" in cfg
        assert "classification" in cfg

    def test_get_with_dotpath(self, test_env):
        val = get("search.max_per_dim")
        assert val == 5

    def test_get_default(self, test_env):
        val = get("nonexistent.key", "fallback")
        assert val == "fallback"

    def test_custom_config_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.yaml")
            with open(cfg_path, "w") as f:
                f.write("search:\n  max_per_dim: 99\n")
            os.environ["_TEST_HFPAPERS_CONFIG"] = cfg_path
            cfg = load_config(reload=True)
            assert get("search.max_per_dim") == 99
            del os.environ["_TEST_HFPAPERS_CONFIG"]
            # Clear cache so subsequent tests don't see this mini config
            from hfpapers.config import _config_cache
            _config_cache = None


class TestBudget:
    def test_estimate_cost_deepseek(self):
        cost = estimate_cost("deepseek/deepseek-chat", 10000, 500)
        assert cost > 0

    def test_check_token_budget_within_limit(self):
        assert check_token_budget(1000, 500)

    def test_check_token_budget_exceeded(self):
        assert not check_token_budget(100000, 50000)

    def test_check_cost_budget_free_model(self):
        # Local models like Ollama return True (free)
        assert check_cost_budget("ollama/llama3", 100000, 50000)

    def test_check_cost_budget_exceeded(self):
        assert check_cost_budget("deepseek/deepseek-chat", 500000, 100000, max_cost_usd=0.01) is False
