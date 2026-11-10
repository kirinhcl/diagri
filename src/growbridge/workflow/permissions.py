"""Who may drive the workflow. Identities come from the server, never from model output."""

from collections.abc import Collection

from growbridge.ports import Actor, Denied

REAUTH_SECONDS = 300


def require_kind(actor: Actor, allowed: Collection[str]) -> None:
    """Deny an identity whose kind is not in ``allowed``; model identities get their own code."""
    if actor.kind in allowed:
        return
    if actor.kind == "model":
        raise Denied("model_role", "model roles have no stage or approval controls")
    raise Denied("not_operator", f"{actor.kind} identities may not do this")


def require_operator(actor: Actor, now: float, recent: bool = False) -> None:
    """The actor must be an authenticated operator, with a recent re-authentication if asked."""
    require_kind(actor, ("operator",))
    if recent and (actor.reauth_at is None or now - actor.reauth_at > REAUTH_SECONDS):
        raise Denied("reauth_required", f"re-authenticate within {REAUTH_SECONDS} seconds")
