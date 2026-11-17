"""The reasons and limitations the server adds to a research report, in both console languages.

Each note has a stable ``code`` and its ``params``; ``text`` gives it in English (``en``) and
Chinese (``zh``), the two languages of the workbench. A report stores every server note with
both texts, so the console shows it in the viewer's language, while the report's plain-text
fields keep the Chinese text they always had.
"""

from typing import Any

from growbridge.archive.models import Model

LANGUAGES = ("en", "zh")
TEXT_LANGUAGE = "zh"  # the language of the plain-text fields (reasons, limitations)

TEMPLATES: dict[str, dict[str, str]] = {
    "no_replicates": {
        "en": "No independent replicate of the treatments: the observed difference can be "
        "described, but no treatment effect can be inferred",
        "zh": "缺少独立的处理重复：只能描述已观察到的差异，不能推断处理效应",
    },
    "confounded_with_time": {
        "en": "The treatment cannot be told apart from time or growth stage: only the change "
        "over time can be described",
        "zh": "处理与时间或生长期无法区分：只能描述随时间的变化",
    },
    "missing_over_limit": {
        "en": "More data is missing than the protocol allows: the result is only an "
        "exploratory lead",
        "zh": "缺失超过预定标准：结果只能作为探索性线索",
    },
    "changed_after_outcomes": {
        "en": "The endpoint, exclusion rules or analysis changed after the outcome data was "
        "seen: the result is only exploratory",
        "zh": "看到结局数据后变更了终点、排除规则或分析方法：结果只能作为探索",
    },
    "deviation_over_limit": {
        "en": "The treatment actually delivered left the approved plan more often than the "
        "protocol allows: the result is only exploratory",
        "zh": "实际处理偏离批准范围，超过协议预定的比例：结果只能作为探索",
    },
    "snapshot_incomplete": {
        "en": "The data snapshot is incomplete (coverage {coverage}): it cannot carry a "
        "confirmatory result",
        "zh": "数据快照不完整（覆盖率 {coverage}）：不能作为确认性结果",
    },
    "no_confirmatory_run": {
        "en": "No confirmatory analysis run frozen on this data snapshot is recorded: the "
        "result cannot be confirmatory",
        "zh": "没有该数据快照上已冻结的确认性分析记录：不能作为确认性结果",
    },
    "holdout_read": {
        "en": "The holdout set was read before: this read can only be exploratory",
        "zh": "留出集已被读取过：本次读取只能作为探索性结果",
    },
    "unallocated_measurements": {
        "en": "{count} measurements have no matching allocation and were left out",
        "zh": "{count} 条测量没有对应的分配，未计入",
    },
    "treatment_not_applied": {
        "en": "Round {round} did not run its allocated treatment {treatment}: {problems}",
        "zh": "第 {round} 轮没有按分配的处理 {treatment} 运行：{problems}",
    },
    "treatment_unverified": {
        "en": "The samples of round {round} record no level for {channels}, so whether "
        "treatment {treatment} was applied cannot be checked",
        "zh": "第 {round} 轮的样本没有记录 {channels} 的档位，无法核对处理 {treatment} 是否执行",
    },
    "manual_tasks_missed": {
        "en": "Round {round}: {missed} of {total} planned manual tasks were not done on time "
        "({by_kind})",
        "zh": "第 {round} 轮：计划的 {total} 次人工任务中有 {missed} 次没有按时完成（{by_kind}）",
    },
    "manual_tasks_unsettled": {
        "en": "Round {round}: {open} of {planned} planned manual tasks were not yet due or still "
        "within their time when the data was frozen, so they were not checked",
        "zh": "第 {round} 轮：冻结数据时，计划的 {planned} 次人工任务中有 {open} 次还没到期或仍在"
        "时限内，未参与核对",
    },
    "manual_tasks_unchecked": {
        "en": "Not every manual task could be checked (data frozen before their deadline): the "
        "result can only be exploratory",
        "zh": "人工任务没有全部核对（数据在截止前冻结）：结果只能是探索性的",
    },
}


class Note(Model):
    """One server note: a code from ``TEMPLATES`` and the values its texts name."""

    code: str
    params: dict[str, Any] = {}

    def text(self, language: str = TEXT_LANGUAGE) -> str:
        template = TEMPLATES[self.code][language]
        return template.format(
            **{key: _shown(key, value, language) for key, value in self.params.items()}
        )

    def texts(self) -> dict[str, str]:
        return {language: self.text(language) for language in LANGUAGES}

    def entry(self, kind: str) -> dict[str, Any]:
        """The note as the report stores it; ``kind`` is "reason" or "limitation"."""
        return {"code": self.code, "kind": kind, "params": self.params, "text": self.texts()}


def note(code: str, **params: Any) -> Note:
    if code not in TEMPLATES:
        raise KeyError(f"unknown report note {code}")
    return Note(code=code, params=params)


def _shown(key: str, value: Any, language: str) -> str:
    """One param in ``language``: the structured ones (problems, channels, by_kind, coverage)
    are written out, the rest as they are."""
    if key == "problems" and isinstance(value, (list, tuple)):
        return _JOIN[language].join(_problem_text(item, language) for item in value)
    if key == "channels" and isinstance(value, (list, tuple)):
        return _LIST[language].join(_channel(item, language) for item in value)
    if key == "by_kind" and isinstance(value, dict):
        return _LIST[language].join(_kind_count(k, n, language) for k, n in value.items())
    if key == "coverage" and isinstance(value, (int, float)) and not isinstance(value, bool):
        return _percent(value)
    if isinstance(value, (list, tuple)):
        return "; ".join(str(item) for item in value)
    return str(value)


_JOIN = {"en": "; ", "zh": "；"}
_LIST = {"en": ", ", "zh": "、"}
# the server cannot read the console's catalogs, so the few names a note says live here
_CHANNELS = {
    "light": {"en": "light", "zh": "光照"},
    "exhaust": {"en": "exhaust", "zh": "排风"},
    "fan": {"en": "fan", "zh": "风扇"},
    "pump": {"en": "pump", "zh": "水泵"},
}
_TASK_KINDS = {
    "irrigation": {"en": "irrigation", "zh": "浇水"},
    "measurement": {"en": "measurement", "zh": "测量"},
    "photo": {"en": "photo", "zh": "拍照"},
}
_PROBLEMS = {
    "never_at": {
        "en": "{channel} was never at {level} (recorded {recorded})",
        # light and exhaust levels are percentages, not steps: the text names no unit
        "zh": "{channel}从未达到计划的 {level}（记录到 {recorded}）",
    },
    "other_share": {
        "en": "{channel} was at other levels in {share} of the readings",
        "zh": "{channel}在 {share} 的读数中处于其他档位",
    },
}


def _percent(share: float) -> str:
    return f"{round(100 * share)}%"


def _channel(name: Any, language: str) -> str:
    return _CHANNELS.get(str(name), {}).get(language, str(name))


def _kind_count(kind: Any, count: Any, language: str) -> str:
    name = _TASK_KINDS.get(str(kind), {}).get(language, str(kind))
    return f"{name} {count}" if language == "en" else f"{name} {count} 次"


def _problem_text(item: Any, language: str) -> str:
    template = _PROBLEMS.get(item.get("kind")) if isinstance(item, dict) else None
    if template is None:
        return str(item)
    return template[language].format(
        channel=_channel(item.get("channel"), language),
        level=item.get("level"),
        recorded=", ".join(str(level) for level in item.get("recorded") or ()),
        share=_percent(item.get("share") or 0),
    )
