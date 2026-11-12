"""Process-wide logging setup for ``growbridge serve``.

The one place that configures logging. httpx and httpcore log every request URL at INFO, and some
URLs are secrets: a heartbeat ping URL, and the Telegram Bot API path ``/bot<token>/sendMessage``.
Their loggers are therefore held at WARNING whatever level the rest of the process uses. Our own
code logs exception types only, never messages, URLs or credentials.
"""

import logging

QUIET_LIBRARIES = ("httpx", "httpcore")


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level)
    logging.getLogger().setLevel(level)
    for name in QUIET_LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)
