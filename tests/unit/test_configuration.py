"""Unit tests for configuration, validation, and environment overrides."""

import os
import pytest
from pathlib import Path

from headway.core.configuration import (
    AppConfig,
    DirectoryConfig,
    EnvironmentType,
    GradioServerConfig,
    is_running_in_colab,
)
from headway.core.exceptions import ConfigurationError


@pytest.mark.unit
def test_default_configuration_initialization(temp_storage_dir: Path):
    """Verify that default AppConfig instantiates with valid parameters."""
    dirs = DirectoryConfig(base_dir=temp_storage_dir)
    config = AppConfig(directories=dirs)
    assert config.version == "0.1.0-dev"
    assert config.log_level in AppConfig.VALID_LOG_LEVELS
    assert config.server.share is False  # Safe default requirement
    assert config.server.server_port == 7860


@pytest.mark.unit
def test_environment_override_parsing(monkeypatch, temp_storage_dir: Path):
    """Verify that environment variables properly override configuration."""
    monkeypatch.setenv("HEADWAY_ENV", "production")
    monkeypatch.setenv("HEADWAY_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("HEADWAY_DEV_MODE", "false")
    monkeypatch.setenv("HEADWAY_SERVER_PORT", "8080")
    monkeypatch.setenv("HEADWAY_SERVER_NAME", "127.0.0.1")
    monkeypatch.setenv("HEADWAY_SERVER_SHARE", "false")

    dirs = DirectoryConfig(base_dir=temp_storage_dir)
    config = AppConfig(directories=dirs)

    assert config.environment == EnvironmentType.PRODUCTION
    assert config.log_level == "WARNING"
    assert config.dev_mode is False
    assert config.server.server_port == 8080
    assert config.server.server_name == "127.0.0.1"
    assert config.server.share is False


@pytest.mark.unit
def test_invalid_log_level_validation(temp_storage_dir: Path):
    """Verify that invalid log level raises ConfigurationError."""
    dirs = DirectoryConfig(base_dir=temp_storage_dir)
    with pytest.raises(ConfigurationError) as exc_info:
        AppConfig(log_level="VERBOSE_INVALID", directories=dirs)
    assert exc_info.value.error_code == "ERR_CORE_CONFIG_LOG_LEVEL"


@pytest.mark.unit
def test_invalid_server_port_validation():
    """Verify that out-of-range server port raises ConfigurationError."""
    server_cfg = GradioServerConfig(server_port=99)
    with pytest.raises(ConfigurationError) as exc_info:
        server_cfg.validate()
    assert exc_info.value.error_code == "ERR_CORE_CONFIG_PORT"

    server_cfg_high = GradioServerConfig(server_port=70000)
    with pytest.raises(ConfigurationError):
        server_cfg_high.validate()


@pytest.mark.unit
def test_empty_server_name_validation():
    """Verify that empty server name raises ConfigurationError."""
    server_cfg = GradioServerConfig(server_name="")
    with pytest.raises(ConfigurationError) as exc_info:
        server_cfg.validate()
    assert exc_info.value.error_code == "ERR_CORE_CONFIG_SERVER_NAME"


@pytest.mark.unit
def test_config_to_dict(test_config: AppConfig):
    """Verify config dictionary serialization."""
    d = test_config.to_dict()
    assert d["version"] == "0.1.0-dev"
    assert d["environment"] == "testing"
    assert d["server_share"] is False


@pytest.mark.unit
def test_colab_detection():
    """Verify colab detection helper returns boolean."""
    result = is_running_in_colab()
    assert isinstance(result, bool)
