"""Integration tests for CLI launcher argument parsing."""

import pytest
from headway.__main__ import parse_args


@pytest.mark.integration
def test_cli_argument_parsing(monkeypatch):
    """Verify that CLI flags parse properly into options."""
    monkeypatch.setattr(
        "sys.argv",
        [
            "headway-sim",
            "--host",
            "127.0.0.1",
            "--port",
            "8888",
            "--log-level",
            "DEBUG",
            "--dev",
        ],
    )
    args = parse_args()
    assert args.host == "127.0.0.1"
    assert args.port == 8888
    assert args.log_level == "DEBUG"
    assert args.dev is True
    assert args.share is False
