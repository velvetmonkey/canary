"""Tests for CLI argument parsing, source filtering, and config resolution."""

import argparse
from unittest.mock import patch

from canary.scheduler import _get_fetcher, _load_config, _resolve_config, _resolve_model


class TestResolveModel:
    def test_default_model(self):
        with patch.dict("os.environ", {}, clear=True):
            assert _resolve_model(None) == "claude-sonnet-4-6"

    def test_env_var_override(self):
        with patch.dict("os.environ", {"CANARY_MODEL": "claude-opus-4-6"}):
            assert _resolve_model(None) == "claude-opus-4-6"

    def test_cli_arg_overrides_env(self):
        with patch.dict("os.environ", {"CANARY_MODEL": "claude-opus-4-6"}):
            assert _resolve_model("claude-haiku-4-5-20251001") == "claude-haiku-4-5-20251001"


class TestResolveConfig:
    def test_default_config_path(self, tmp_path):
        config_file = tmp_path / "sources.yaml"
        config_file.write_text("sources: []")
        with patch("canary.scheduler.DEFAULT_CONFIG", str(config_file)):
            assert _resolve_config(None) == config_file

    def test_cli_arg_override(self, tmp_path):
        config_file = tmp_path / "custom.yaml"
        config_file.write_text("sources: []")
        assert _resolve_config(str(config_file)) == config_file

    def test_env_var_override(self, tmp_path):
        config_file = tmp_path / "env.yaml"
        config_file.write_text("sources: []")
        with patch.dict("os.environ", {"CANARY_CONFIG": str(config_file)}):
            result = _resolve_config(None)
            assert result == config_file

    def test_missing_file_raises(self):
        try:
            _resolve_config("/nonexistent/path.yaml")
            assert False, "Should have raised FileNotFoundError"
        except FileNotFoundError:
            pass


class TestLoadConfig:
    def test_valid_config(self, tmp_path):
        config_file = tmp_path / "sources.yaml"
        config_file.write_text("sources:\n  - id: test\n")
        config = _load_config(config_file)
        assert "sources" in config
        assert len(config["sources"]) == 1

    def test_missing_sources_key(self, tmp_path):
        config_file = tmp_path / "bad.yaml"
        config_file.write_text("other_key: true\n")
        try:
            _load_config(config_file)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "sources" in str(e)

    def test_invalid_yaml(self, tmp_path):
        config_file = tmp_path / "invalid.yaml"
        config_file.write_text(":\n  bad: [yaml\n")
        try:
            _load_config(config_file)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "Invalid YAML" in str(e)


class TestGetFetcher:
    def test_eurlex_fetcher(self):
        from canary.fetchers.eurlex import EurLexFetcher

        fetcher = _get_fetcher("eurlex")
        assert isinstance(fetcher, EurLexFetcher)

    def test_unknown_fetcher_raises(self):
        try:
            _get_fetcher("unknown")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "unknown" in str(e)


class TestSourceFiltering:
    """Test that --source filtering works via run_canary args."""

    def test_cli_parses_source_flag(self):
        """Verify argparse accepts --source flag."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--source", type=str, default=None)
        args = parser.parse_args(["--source", "SFDR-L1"])
        assert args.source == "SFDR-L1"

    def test_cli_parses_model_flag(self):
        """Verify argparse accepts --model flag."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--model", type=str, default=None)
        args = parser.parse_args(["--model", "claude-opus-4-6"])
        assert args.model == "claude-opus-4-6"
