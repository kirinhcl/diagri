"""What every workbench route module shares: the request body base, the request id pattern and
the answer to a body that is well-formed but not acceptable."""

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict

REQUEST_ID = r"^[a-zA-Z0-9_-]{8,100}$"
UNPROCESSABLE = 422


def rejected(message: str) -> HTTPException:
    return HTTPException(UNPROCESSABLE, detail={"code": "param", "message": message})


class Body(BaseModel):
    """Unknown fields are dropped: an identity or permission in a body never counts."""

    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)
