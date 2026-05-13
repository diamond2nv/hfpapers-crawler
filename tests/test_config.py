"""测试 config 模块 — YAML 加载 + env 合并 + budget 检查"""
import os
import tempfile
from hfpapers.config import load_config, get, estimate_cost, check_token_budget, check_cost_budget


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
            # 清空缓存，避免后续测试读到这个 mini 配置
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
        # Ollama 等本地模型返回 True（不花钱）
        assert check_cost_budget("ollama/llama3", 100000, 50000)

    def test_check_cost_budget_exceeded(self):
        assert check_cost_budget("deepseek/deepseek-chat", 500000, 100000, max_cost_usd=0.01) is False
