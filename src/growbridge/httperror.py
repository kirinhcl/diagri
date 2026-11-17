"""An HTTP refusal of the root app (``/api``) that names what went wrong.

The body keeps ``detail`` as the plain string old clients read and adds the coarse ``code``, the
registered ``reason`` and the ``params`` beside it, at the top level."""

from collections.abc import Mapping

from .jsonsafe import json_safe


class CodedHTTPError(Exception):
    def __init__(
        self,
        status: int,
        message: str,
        *,
        code: str,
        reason: str,
        params: Mapping[str, object] | None = None,
    ):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code
        self.reason = reason
        self.params = dict(params or {})

    def body(self) -> dict[str, object]:
        return {
            "detail": json_safe(self.message),
            "code": self.code,
            "reason": self.reason,
            "params": json_safe(self.params),
        }
