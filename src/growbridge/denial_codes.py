"""The registry of denial reasons: ``DENIAL_CODES[reason]`` is a ``Code`` whose ``of`` is the
coarse ``Denied`` code it refines and whose ``params`` are the values a refusal carries.

A refusal is ``Denied(code, message, reason=..., params=...)``. The console builds its two
sentences from the reason and params; the English message stays for logs and the model. The
registry is merged into ``growbridge.codes.CODES`` as the ``denial`` family.
"""

from __future__ import annotations

# Bound before the import below: growbridge.codes imports this module while it loads.
DENIAL_CODES: dict[str, Code] = {}

from growbridge.codes import Code  # noqa: E402
