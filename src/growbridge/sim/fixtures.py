"""Synthetic run sheets, protocols and safety configs shared by tests and simulated runs."""

from growbridge.archive.models import (
    Allocation,
    AnalysisPlan,
    Channel,
    ChannelPlan,
    Condition,
    FeedbackRule,
    Ownership,
    ProtectionRule,
    ResearchProtocol,
    RuleAction,
    RunSheet,
    SafetyConfig,
    SamplingPlan,
    TimedAction,
    Treatment,
)

DEVICE = "SIMULATED"
TIMEZONE = "Europe/Helsinki"


HIGH_LIGHT = 70  # make_protocol's treatment "high", allocated to rounds 1 and 4


def light_day(level: int) -> tuple[TimedAction, ...]:
    """Light at ``level`` % from 06:00 to 22:00, exhaust 30 % all day."""
    return (
        TimedAction(id="light-on", channel=Channel.LIGHT, at="06:00", level=level),
        TimedAction(id="light-off", channel=Channel.LIGHT, at="22:00", level=0),
        TimedAction(id="exhaust-base", channel=Channel.EXHAUST, at="00:00", level=30),
    )


def treated_run_sheet(**overrides) -> RunSheet:
    """``make_run_sheet`` with the light at round 1's treatment ("high", 70 %) of
    ``make_protocol``, as the workflow requires of a sheet filed for that round."""
    return make_run_sheet(**{"timed_actions": light_day(HIGH_LIGHT), **overrides})


def make_run_sheet(**overrides) -> RunSheet:
    """Light 60 % from 06:00 to 22:00, exhaust 30 % all day; every channel host-controlled.
    60 % is neither of ``make_protocol``'s treatments: see ``treated_run_sheet``."""
    fields = {
        "id": "sheet-1",
        "project_id": "project-1",
        "experiment_id": "experiment-1",
        "stage_id": "stage-1",
        "protocol_id": "protocol-1",
        "protocol_version": 1,
        "device_id": DEVICE,
        "version": 1,
        "timezone": TIMEZONE,
        "channels": (
            ChannelPlan(channel=Channel.LIGHT, ownership=Ownership.HOST, retained_level=0),
            ChannelPlan(channel=Channel.EXHAUST, ownership=Ownership.HOST, retained_level=30),
            ChannelPlan(channel=Channel.FAN, ownership=Ownership.HOST, retained_level=1),
            ChannelPlan(channel=Channel.PUMP, ownership=Ownership.HOST, retained_level=0),
        ),
        "duration_seconds": 7 * 86400,
        "sampling": SamplingPlan(interval_seconds=1, max_gap_seconds=120),
        "max_wait_seconds": 6 * 3600,
        "timed_actions": light_day(60),
    }
    return RunSheet(**{**fields, **overrides})


def humidity_rule(**overrides) -> FeedbackRule:
    """Ordinary humidity feedback: above 70 % for 60 s raises exhaust, below 60 % releases it."""
    fields = {
        "id": "humidity-exhaust",
        "sensor": "humi",
        "position": "canopy",
        "unit": "%",
        "validity_seconds": 20,
        "trigger": Condition(op=">", value=70),
        "recover": Condition(op="<", value=60),
        "duration_seconds": 60,
        "action": RuleAction(channel=Channel.EXHAUST, level=80),
        "release": RuleAction(channel=Channel.EXHAUST, level=30),
        "min_switch_seconds": 120,
    }
    return FeedbackRule(**{**fields, **overrides})


def make_safety(**overrides) -> SafetyConfig:
    """Overheat protection: above 35 °C for 30 s switches the light off."""
    rule = ProtectionRule(
        id="overheat-light-off",
        sensor="temp",
        unit="C",
        validity_seconds=20,
        trigger=Condition(op=">", value=35),
        duration_seconds=30,
        action=RuleAction(channel=Channel.LIGHT, level=0),
    )
    return SafetyConfig(**{"version": 1, "rules": (rule,), **overrides})


def make_protocol(**overrides) -> ResearchProtocol:
    """Single-tent series: four rounds in two blocks, treatment order randomized per block."""
    fields = {
        "id": "protocol-1",
        "project_id": "project-1",
        "version": 1,
        "question": "提高光照后，冠层增长是否加快？",
        "hypothesis": "70 % 光照下冠层面积日增长高于 40 %。",
        "crop": "lettuce",
        "crop_taxon": "NCBITaxon:4236",  # Lactuca sativa, NCBI Taxonomy
        "batch": "batch-1",
        "treatments": (
            Treatment(id="control", name="light 40 %", factors={"light": 40}),
            Treatment(id="high", name=f"light {HIGH_LIGHT} %", factors={"light": HIGH_LIGHT}),
        ),
        "control_treatment_id": "control",
        "allocations": (
            Allocation(round=1, block=1, unit="tent-1", treatment_id="high"),
            Allocation(round=2, block=1, unit="tent-1", treatment_id="control"),
            Allocation(round=3, block=2, unit="tent-1", treatment_id="control"),
            Allocation(round=4, block=2, unit="tent-1", treatment_id="high"),
        ),
        "randomization_seed": 20261118,  # reproduces the allocations above
        "analysis": AnalysisPlan(
            primary_endpoint="canopy_area_growth", target_effect=0.15, method="paired_block"
        ),
        "stages": ("vegetative",),
        "rounds": 4,
        "blocks": 2,
        "variables": ("canopy_area_growth",),
    }
    return ResearchProtocol(**{**fields, **overrides})
