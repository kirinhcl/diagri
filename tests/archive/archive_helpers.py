from growbridge.ports import RawSample


class ListSource:
    """A SampleSource over a fixed list, like a legacy store that keeps its own cursor."""

    def __init__(self, samples):
        self.samples = list(samples)

    def read_after(self, cursor, limit):
        return [s for s in self.samples if s.cursor > cursor][:limit]


def raw(cursor, at, **data):
    return RawSample(cursor=cursor, received_at=at, captured_at=at, data=data or {"t": 1.0})
