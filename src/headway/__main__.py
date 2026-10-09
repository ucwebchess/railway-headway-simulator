"""Command-line execution entry point for Railway Headway & Capacity Simulator.

Supports launching the Gradio interface via:
    python -m headway [options]
"""

import argparse
import sys
from headway.core.configuration import AppConfig, GradioServerConfig
from headway.core.logging_config import get_logger, setup_logging
from headway.core.version import __version__
from headway.ui.app import create_app


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for application startup."""
    parser = argparse.ArgumentParser(
        description="Railway Headway & Capacity Simulator — Application Launcher"
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Server host address to bind to (e.g. 0.0.0.0 or 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Server port number (default: 7860)",
    )
    parser.add_argument(
        "--share",
        action="store_true",
        default=False,
        help="Create a public Gradio share link (default: False)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=None,
        help="Application logging severity level",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        default=False,
        help="Run in development mode",
    )
    return parser.parse_args()


def main() -> int:
    """Main application lifecycle execution."""
    args = parse_args()

    # Build config overrides from CLI
    server_kwargs = {}
    if args.host:
        server_kwargs["server_name"] = args.host
    if args.port:
        server_kwargs["server_port"] = args.port
    if args.share:
        server_kwargs["share"] = args.share

    server_cfg = GradioServerConfig(**server_kwargs) if server_kwargs else None

    config_kwargs = {}
    if args.log_level:
        config_kwargs["log_level"] = args.log_level
    if args.dev:
        config_kwargs["dev_mode"] = args.dev
    if server_cfg:
        config_kwargs["server"] = server_cfg

    config = AppConfig(**config_kwargs)

    # Setup logging
    setup_logging(
        level=config.log_level,
        log_dir=config.directories.logs_dir,
    )
    logger = get_logger("main")
    logger.info("Initializing %s v%s", config.app_name, config.version)
    logger.info("Environment: %s | Log Level: %s", config.environment.value, config.log_level)

    try:
        demo = create_app(config)
        logger.info(
            "Launching Gradio interface on %s:%s (share=%s)",
            config.server.server_name,
            config.server.server_port,
            config.server.share,
        )
        demo.launch(
            server_name=config.server.server_name,
            server_port=config.server.server_port,
            share=config.server.share,
            debug=config.server.debug,
            inbrowser=config.server.inbrowser,
            theme=getattr(demo, "app_theme", None),
            css=getattr(demo, "app_css", None),
        )
        return 0
    except Exception as err:
        logger.critical("Fatal error during application execution: %s", err, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
