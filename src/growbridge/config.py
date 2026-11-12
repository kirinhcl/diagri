import os
import secrets
import tomllib
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DEFAULT_MODEL = "claude-opus-5-5"  # the model whose price is built in (agents/llm.py)


def default_config() -> Path:
    return Path.home() / ".config" / "spiderfarmer-growbridge" / "config.toml"


class RoleModel(BaseModel):
    """Model configuration of one Auto Research role (architecture doc §11.7).

    Credentials never live here: the model client resolves them from the environment.
    """

    model_config = ConfigDict(extra="forbid")
    provider: Literal["anthropic"] = "anthropic"
    model: str = DEFAULT_MODEL
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    max_tokens: int = Field(default=16000, ge=256, le=64000)
    max_calls: int = Field(default=20, ge=1)  # model calls in one run of the role
    tools: list[str] = Field(default_factory=list)  # empty: every tool the role allows
    data: list[str] = Field(default_factory=list)  # data kinds the role may read
    # USD per million tokens of ``model``, for the cost budget. Only the default model has a
    # built-in price, so any other model has to state its own.
    input_per_mtok: float | None = Field(default=None, ge=0)
    output_per_mtok: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _priced(self) -> "RoleModel":
        if (self.input_per_mtok is None) != (self.output_per_mtok is None):
            raise ValueError("input_per_mtok and output_per_mtok must be set together")
        if self.model != DEFAULT_MODEL and self.input_per_mtok is None:
            raise ValueError(
                f"model {self.model!r} has no built-in price: set input_per_mtok and "
                "output_per_mtok (USD per million tokens)"
            )
        return self


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device: str
    token: str = Field(min_length=24)
    data_dir: Path
    port: int = Field(default=8766, ge=1024, le=65535)
    controls_enabled: bool = False
    stale_seconds: float = Field(default=20, ge=5, le=120)
    max_pump_seconds: float = Field(default=5, gt=0, le=60)
    pump_cooldown_seconds: float = Field(default=60, ge=0)
    pump_outlet: int = Field(default=4, ge=1, le=5)
    light_outlet: int = Field(default=1, ge=1, le=5)
    exhaust_outlet: int = Field(default=2, ge=1, le=5)
    fan_outlet: int = Field(default=3, ge=1, le=5)
    retention_days: int = Field(default=30, ge=1, le=365)
    # Auto Research (off by default: the daemon then behaves exactly as before).
    auto_research: bool = False
    lan_hosts: list[str] = Field(default_factory=list)  # addresses of the on-site entry
    overlay_hosts: list[str] = Field(default_factory=list)  # addresses of the overlay entry
    # The on-site entry has its own listener: a request is "LAN" only when it was accepted on
    # this address and port, never because of a Host header. Unset means no on-site entry.
    lan_bind: str = ""
    lan_port: int | None = Field(default=None, ge=1024, le=65535)
    report_time: str = Field(default="08:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    report_timezone: str = "UTC"
    roles: dict[str, RoleModel] = Field(default_factory=dict)
    backup_dir: Path | None = None  # independent media for the SQLite online backups
    backup_interval_seconds: float = Field(default=6 * 3600, ge=60)

    @field_validator("report_timezone")
    @classmethod
    def _known_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (KeyError, ValueError, OSError) as error:
            raise ValueError(f"{value!r} is not a known time zone name") from error
        return value

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def load(path: Path | None = None) -> Settings:
    selected = (path or default_config()).expanduser().resolve()
    values = tomllib.loads(selected.read_text())
    values["data_dir"] = Path(values["data_dir"]).expanduser()
    if values.get("backup_dir") is not None:
        values["backup_dir"] = Path(values["backup_dir"]).expanduser()
    settings = Settings(**values)
    mapping = [
        settings.pump_outlet,
        settings.light_outlet,
        settings.exhaust_outlet,
        settings.fan_outlet,
    ]
    if len(set(mapping)) != len(mapping):
        raise ValueError("Each device must have a separate outlet")
    return settings


def initialize(path: Path, device: str, enable_controls: bool = False) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = Path.home() / ".local" / "share" / "spiderfarmer-growbridge"
    # repr-independent TOML strings; JSON basic strings are valid TOML strings here.
    import json

    content = (
        f"device = {json.dumps(device)}\n"
        f"token = {json.dumps(secrets.token_urlsafe(32))}\n"
        f"data_dir = {json.dumps(str(data))}\n"
        f"controls_enabled = {str(enable_controls).lower()}\n"
        "port = 8766\nmax_pump_seconds = 5\npump_cooldown_seconds = 60\n"
        "light_outlet = 1\nexhaust_outlet = 2\nfan_outlet = 3\npump_outlet = 4\n"
    )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(content)
