"""Notification channels at runtime level: what is queued, and what the run health counts."""

from e2e_support import RecordingChannel

UNDELIVERED = "oldest_undelivered_alert"
PAST_THE_LIMIT_BEATS = 20  # 20 beats of 60 s: well past the 900 s limit of the probe


async def run_past_the_limit(world, runtime) -> None:
    for _ in range(PAST_THE_LIMIT_BEATS):
        await world.beat(runtime, 60)


async def test_alert_with_no_channel_configured_does_not_fail_the_run_health(world):
    runtime = await world.boot(channels={})
    assert "backup_unconfigured" in [alert.kind for alert in runtime.book.open()]

    await run_past_the_limit(world, runtime)

    assert UNDELIVERED not in runtime.health.check().failures
    assert "run_health" not in [alert.kind for alert in runtime.book.open()]


async def test_no_channel_configured_is_a_standing_warning_in_the_alert_book(world):
    runtime = await world.boot(channels={})

    standing = [a for a in runtime.book.open() if a.kind == "notify_unconfigured"]

    assert [a.severity for a in standing] == ["warning"]


async def test_configuring_only_email_delivers_open_alerts_and_clears_the_run_health(world):
    first = await world.boot(channels={})
    await world.beat(first, 1)
    await first.stop()

    email = RecordingChannel()
    second = await world.boot(channels={"email": email})
    await run_past_the_limit(world, second)

    assert any("backed up" in text for text in email.sent)
    assert UNDELIVERED not in second.health.check().failures
    assert "notify_unconfigured" not in [alert.kind for alert in second.book.open()]


async def test_notification_left_on_a_channel_without_a_sender_does_not_fail_the_run_health(world):
    runtime = await world.boot(channels={"email": RecordingChannel()})
    runtime.outbox.queue_notification("old-event", "telegram", "queued before the change")

    await run_past_the_limit(world, runtime)

    assert runtime.outbox.status("old-event", "telegram") == "pending"
    assert UNDELIVERED not in runtime.health.check().failures
