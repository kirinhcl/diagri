"""Print the still intervals of a raw demo recording, to choose where edit.py freezes a frame.

    python find_stills.py RAW.mp4 --ffmpeg FFMPEG 158-176 824-849

Each window (raw seconds) is scanned with ffmpeg's freezedetect; a hold placed inside a still
interval freezes a frame where nothing moves, so the cut into and out of it is invisible.
"""

import argparse
import re
import subprocess
import sys

NOISE = "-50dB"
MIN_STILL_SECONDS = 0.8


def stills(ffmpeg: str, raw: str, start: float, end: float) -> list[tuple[float, float]]:
    err = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-ss",
            str(start),
            "-to",
            str(end),
            "-i",
            raw,
            "-an",
            "-vf",
            f"freezedetect=n={NOISE}:d={MIN_STILL_SECONDS}",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    ).stderr
    starts = [float(x) + start for x in re.findall(r"freeze_start: ([0-9.]+)", err)]
    ends = [float(x) + start for x in re.findall(r"freeze_end: ([0-9.]+)", err)]
    return list(zip(starts, ends + [end], strict=False))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("raw")
    parser.add_argument("windows", nargs="+", help="START-END in raw seconds")
    parser.add_argument("--ffmpeg", required=True)
    args = parser.parse_args()
    for window in args.windows:
        start, end = (float(x) for x in window.split("-"))
        found = stills(args.ffmpeg, args.raw, start, end)
        print(f"{window}:", " ".join(f"[{a:.1f}-{b:.1f}]" for a, b in found) or "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
