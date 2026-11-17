"""What every workbench route module shares: the request body base, the request id pattern and
the answer to a body that is well-formed but not acceptable."""

from collections.abc import Mapping

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict

from growbridge.codes import checked_denial
from growbridge.jsonsafe import json_safe

REQUEST_ID = r"^[a-zA-Z0-9_-]{8,100}$"
UNPROCESSABLE = 422


def rejected(
    message: str, *, reason: str | None = None, params: Mapping[str, object] | None = None
) -> HTTPException:
    carried = checked_denial("param", reason, params or {}) if reason else dict(params or {})
    detail = {
        "code": "param",
        "reason": reason,
        "params": json_safe(carried),
        "message": json_safe(message),
    }
    return HTTPException(UNPROCESSABLE, detail=detail)


class Body(BaseModel):
    """Unknown fields are dropped: an identity or permission in a body never counts."""

    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)
