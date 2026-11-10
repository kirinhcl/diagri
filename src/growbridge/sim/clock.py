"""Controllable clock for tests and simulated runs."""

START = 1_800_000_000.0


class FakeClock:
    def __init__(self, now: float = START, synced: bool = True):
        self.wall = now
        self.mono = 1000.0
        self.synced = synced

    def now(self) -> float:
        return self.wall

    def monotonic(self) -> float:
        return self.mono

    def advance(self, seconds: float) -> None:
        """Time passes: both clocks move."""
        self.wall += seconds
        self.mono += seconds

    def jump(self, wall_seconds: float) -> None:
        """The wall clock is stepped (NTP correction, manual change); no time passes."""
        self.wall += wall_seconds
