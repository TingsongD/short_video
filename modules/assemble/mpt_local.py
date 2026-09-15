"""Run vendored MPT with local audio and publishing disabled for this process.

Invoked inside the vendor's Python environment. Does not edit vendor settings.
"""
import sys
from pathlib import Path


def configure_local(config):
    config.app["upload_post_enabled"] = False
    config.app["upload_post_auto_upload"] = False
    config.app["subtitle_provider"] = "whisper"


def main():
    vendor = Path(__file__).resolve().parents[2] / "vendor" / "MoneyPrinterTurbo"
    sys.path.insert(0, str(vendor))
    from app.config import config
    configure_local(config)
    # Vendor config initializes its logger on stdout. Keep the JSON result
    # channel clean when invoking it through this entry point.
    from app.utils.logging_utils import configure_terminal_logger
    configure_terminal_logger(sys.stderr, level=config.log_level, colorize=False)
    import cli
    cli._force_utf8_console()
    return cli.run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
