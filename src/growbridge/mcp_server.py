from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .client import Client

LEGACY_INSTRUCTIONS = (
    "Read get_status before controls. Check health.stale and timestamps. "
    "Use a unique request_id for each intended action and reuse it for retries. "
    "The pump must use run_pump with a finite duration. A successful write means "
    "the controller state was read back; physical operation needs observation. "
    "GrowBridge daemon must already be running."
)
READ_ONLY_INSTRUCTIONS = (
    "This deployment is read-only for MCP clients: device and stage control belongs to the "
    "workbench and its human operators. Check health.stale and timestamps in get_status. "
    "GrowBridge daemon must already be running."
)


def _register_reads(server: FastMCP, client: Client) -> None:
    read = ToolAnnotations(readOnlyHint=True, openWorldHint=False)

    @server.tool(annotations=read)
    async def get_health() -> dict:
        """Read BLE availability, freshness, protocol support, and the configured outlet mapping."""
        return await client.call("GET", "/health")

    @server.tool(annotations=read)
    async def get_status() -> dict:
        """Read current environment and device state; inspect health.stale and last_sample_at."""
        return await client.call("GET", "/status")

    @server.tool(annotations=read)
    async def get_history(hours: float = 24, limit: int = 500) -> dict:
        """Read up to 168 hours of observations, limit 1..2000. Starts at installation."""
        return await client.call("GET", "/history", params={"hours": hours, "limit": limit})


def _register_writes(server: FastMCP, client: Client) -> None:
    write = ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False
    )

    @server.tool(annotations=write)
    async def set_light(brightness_percent: int, request_id: str) -> dict:
        """Set manual light brightness 0..100; 0 is off. Power outlet is controlled separately."""
        return await client.call(
            "POST", "/control/light", {"level": brightness_percent, "request_id": request_id}
        )

    @server.tool(annotations=write)
    async def set_exhaust(speed_percent: int, request_id: str) -> dict:
        """Set the exhaust blower to manual speed 0..100; 0 turns it off."""
        return await client.call(
            "POST", "/control/exhaust", {"level": speed_percent, "request_id": request_id}
        )

    @server.tool(annotations=write)
    async def set_fan(level: int, request_id: str) -> dict:
        """Set the circulation fan to manual gear 0..10; 0 turns it off."""
        return await client.call("POST", "/control/fan", {"level": level, "request_id": request_id})

    @server.tool(annotations=write)
    async def set_outlet(number: int, on: bool, request_id: str) -> dict:
        """Switch a configured power outlet. Pump outlet ON is blocked; use run_pump."""
        return await client.call(
            "POST", "/outlet", {"number": number, "on": on, "request_id": request_id}
        )

    @server.tool(annotations=write)
    async def run_pump(seconds: float, request_id: str) -> dict:
        """Run a finite pulse and confirm OFF before returning.

        Default maximum 5 seconds, cooldown 60 seconds. Reuse request_id for retries.
        """
        return await client.call("POST", "/pump", {"seconds": seconds, "request_id": request_id})


def create_mcp(settings):
    """With ``settings.auto_research`` only the three read tools exist: model roles and generic
    MCP clients have no device tools (architecture §10)."""
    client = Client(settings)
    read_only = settings.auto_research
    server = FastMCP(
        "spiderfarmer-growbridge",
        instructions=READ_ONLY_INSTRUCTIONS if read_only else LEGACY_INSTRUCTIONS,
    )
    _register_reads(server, client)
    if not read_only:
        _register_writes(server, client)
    return server
