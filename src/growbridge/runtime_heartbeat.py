"""External heartbeat wiring for ``growbridge serve`` (architecture doc section 8.2).

Both endpoints or none. Watching only the host, or only the run, would look like monitoring while
half of the failures go unseen, so a single URL refuses to start. The URLs are secrets: they are
read from the environment when a signal is sent and appear in no log, alert, error or ``repr``.
"""

import os

import httpx

from growbridge.observer.channels import HeartbeatChannel

HOST_ENV = "GROWBRIDGE_HEARTBEAT_HOST_URL"
RUN_ENV = "GROWBRIDGE_HEARTBEAT_RUN_URL"
UNCONFIGURED_MESSAGE = (
    f"No external heartbeat is configured ({HOST_ENV} and {RUN_ENV}): "
    "nobody is told if this host or the run stops"
)


def _configured(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def heartbeats_from_env(
    client: httpx.AsyncClient | None = None,
) -> tuple[HeartbeatChannel, HeartbeatChannel] | None:
    """The (host, run) heartbeat pair, or ``None`` when neither URL is set.

    Raises ``ValueError`` when only one of them is set; the message names variables, not values.
    """
    host, run = _configured(HOST_ENV), _configured(RUN_ENV)
    if host != run:
        missing = RUN_ENV if host else HOST_ENV
        present = HOST_ENV if host else RUN_ENV
        raise ValueError(
            f"{present} is set but {missing} is not: configure both external heartbeats or neither"
        )
    if not host:
        return None
    return HeartbeatChannel(HOST_ENV, client), HeartbeatChannel(RUN_ENV, client)
