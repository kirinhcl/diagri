"""Round, stage and research-task states (architecture doc Appendix B).

This module imports nothing from the rest of the package so that the shared models can use it.
"""

from enum import StrEnum


class RoundState(StrEnum):
    DESIGNING = "designing"
    STAGE_REVIEW = "stage_review"
    STAGE_RUNNING = "stage_running"
    DATA_VERIFICATION = "data_verification"
    ANALYSIS = "analysis"
    DELIVERED = "delivered"
    ABORTED = "aborted"


class StageState(StrEnum):
    PENDING_REVIEW = "pending_review"
    RUNNING = "running"
    PAUSED = "paused"
    MANUAL = "manual"
    RECOVERY_CHECK = "recovery_check"
    ENDED = "ended"
    STOPPED = "stopped"


class TaskState(StrEnum):
    IN_PROGRESS = "in_progress"
    REMOTE_QUEUED = "remote_queued"
    COMPUTING = "computing"
    FETCHING = "fetching"
    RECONCILE = "reconcile"
    NEEDS_ATTENTION = "needs_attention"
    NEEDS_REVIEW = "needs_review"
    DONE = "done"
    ENDED = "ended"


LABELS: dict[StrEnum, str] = {
    RoundState.DESIGNING: "设计中",
    RoundState.STAGE_REVIEW: "阶段待审",
    RoundState.STAGE_RUNNING: "阶段进行中",
    RoundState.DATA_VERIFICATION: "数据核验",
    RoundState.ANALYSIS: "研究分析",
    RoundState.DELIVERED: "已交付归档",
    RoundState.ABORTED: "已中止归档",
    StageState.PENDING_REVIEW: "待审",
    StageState.RUNNING: "执行中",
    StageState.PAUSED: "已暂停",
    StageState.MANUAL: "人工接管",
    StageState.RECOVERY_CHECK: "恢复待核对",
    StageState.ENDED: "已结束",
    StageState.STOPPED: "已停止",
    TaskState.IN_PROGRESS: "进行中",
    TaskState.REMOTE_QUEUED: "远程排队",
    TaskState.COMPUTING: "计算中",
    TaskState.FETCHING: "产物回收",
    TaskState.RECONCILE: "待对账",
    TaskState.NEEDS_ATTENTION: "待处理",
    TaskState.NEEDS_REVIEW: "待复核",
    TaskState.DONE: "完成",
    TaskState.ENDED: "已结束",
}

ROUND_TERMINAL = frozenset({RoundState.DELIVERED, RoundState.ABORTED})
STAGE_TERMINAL = frozenset({StageState.ENDED, StageState.STOPPED})
TASK_TERMINAL = frozenset({TaskState.DONE, TaskState.ENDED})
