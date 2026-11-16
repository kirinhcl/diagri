"""One way to build a run sheet Finding: a stable code, an optional variant, and params.

The message code the console looks up is ``code`` when ``variant`` is empty, else
``code.variant``; ``Finding.code`` itself (the group the console titles) never changes. The
English ``message`` stays for API clients and logs; the console builds its text from the code
and params.
"""

from growbridge.codes import checked
from growbridge.ports import Finding

# English wording of a source kind; ``{}`` takes the source's name.
SOURCE_ENGLISH = {
    "timed_action": "timed action {}",
    "feedback_rule": "feedback rule {}",
    "feedback_release": "feedback rule {} release",
    "care_step": "care step {}",
    "end_action": "end action {}",
    "protection_rule": "protection rule {}",
}


def source_text(kind: str, source: str) -> str:
    return SOURCE_ENGLISH[kind].format(source)


def message_code(code: str, variant: str) -> str:
    return f"{code}.{variant}" if variant else code


def make_finding(
    code: str, message: str, *, blocking: bool, variant: str = "", **params: object
) -> Finding:
    return Finding(
        code=code,
        message=message,
        blocking=blocking,
        variant=variant,
        params=checked("finding", message_code(code, variant), params),
    )


def block(code: str, message: str, *, variant: str = "", **params: object) -> Finding:
    return make_finding(code, message, blocking=True, variant=variant, **params)


def hint(code: str, message: str, *, variant: str = "", **params: object) -> Finding:
    return make_finding(code, message, blocking=False, variant=variant, **params)
