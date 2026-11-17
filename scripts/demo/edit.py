"""Turn the raw demo recording into the final video, using the recorder's timeline.

Time-lapse marks (the waits for the model roles and the fast-forwarded stage) are squeezed to
their target length, cut marks are dropped, everything else plays at real speed. Optional holds
freeze a still frame for a few seconds where there is text to read (agent replies, the report).
Each piece is encoded on its own with the same settings and the pieces are joined without
re-encoding, so memory stays flat however long the recording is. Writes the final MP4 with
embedded chapters and a chapters.txt with the same timestamps.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

FPS = 25
CRF = 18
TIMESCALE = "12800"  # identical in every piece, so the concat demuxer can join them losslessly
MIN_PIECE_SECONDS = 0.05
FIRST_CHAPTER = "Introduction, sign-in and a tour of the workbench"
ENCODE = [
    "-c:v",
    "libx264",
    "-preset",
    "slow",
    "-crf",
    str(CRF),
    "-r",
    str(FPS),
    "-pix_fmt",
    "yuv420p",
    "-video_track_timescale",
    TIMESCALE,
]


def plan(timeline: dict) -> list[dict]:
    """Play pieces in raw seconds, in order, covering the kept parts of the recording."""
    duration = timeline["duration"]
    marks = sorted(
        (m for m in timeline["marks"] if m.get("end") is not None), key=lambda m: m["start"]
    )
    pieces: list[dict] = []
    cursor = 0.0

    def play(start: float, end: float, speed: float) -> None:
        if end - start > MIN_PIECE_SECONDS:
            pieces.append({"kind": "play", "start": start, "end": end, "speed": speed})

    for mark in marks:
        start, end = max(mark["start"], cursor), min(mark["end"], duration)
        play(cursor, start, 1.0)
        if mark["type"] == "speed":
            play(start, end, max(1.0, (end - start) / mark["target"]))
        cursor = max(cursor, end)
    play(cursor, duration, 1.0)
    return pieces


def insert_holds(pieces: list[dict], holds: list[dict]) -> list[dict]:
    """Split real-speed pieces at each hold time and put a still of that frame in between."""
    out = list(pieces)
    for hold in sorted(holds, key=lambda h: h["t"]):
        t = hold["t"]
        for index, piece in enumerate(out):
            inside = piece["kind"] == "play" and piece["start"] < t < piece["end"]
            if not inside:
                continue
            if piece["speed"] != 1.0:
                raise ValueError(f"hold at {t} s falls inside a time-lapse")
            out[index : index + 1] = [
                {**piece, "end": t},
                {
                    "kind": "hold",
                    "t": t,
                    "seconds": hold["seconds"],
                    "label": hold.get("label", ""),
                },
                {**piece, "start": t},
            ]
            break
        else:
            raise ValueError(f"hold at {t} s is outside the kept recording")
    return out


def length(piece: dict) -> float:
    if piece["kind"] == "hold":
        return piece["seconds"]
    return (piece["end"] - piece["start"]) / piece["speed"]


def to_output(t: float, pieces: list[dict]) -> float:
    """Where raw second ``t`` lands in the edited video."""
    out = 0.0
    for piece in pieces:
        if piece["kind"] == "hold":
            if piece["t"] < t:
                out += piece["seconds"]
            continue
        if t <= piece["start"]:
            break
        out += (min(t, piece["end"]) - piece["start"]) / piece["speed"]
    return out


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({result.returncode}): {result.stderr[-800:]}")


def encode_play(ffmpeg: str, raw: Path, piece: dict, out: Path) -> None:
    video_filter = (
        f"setpts=(PTS-STARTPTS)/{piece['speed']:.5f},fps={FPS},"
        "scale=in_range=pc:out_range=tv,format=yuv420p"
    )
    run(
        [
            ffmpeg,
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{piece['start']:.3f}",
            "-to",
            f"{piece['end']:.3f}",
            "-i",
            str(raw),
            "-an",
            "-vf",
            video_filter,
            *ENCODE,
            str(out),
        ]
    )


def encode_hold(ffmpeg: str, raw: Path, piece: dict, out: Path) -> None:
    still = out.with_suffix(".png")
    run(
        [
            ffmpeg,
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{piece['t']:.3f}",
            "-i",
            str(raw),
            "-frames:v",
            "1",
            str(still),
        ]
    )
    run(
        [
            ffmpeg,
            "-loglevel",
            "error",
            "-y",
            "-loop",
            "1",
            "-framerate",
            str(FPS),
            "-t",
            f"{piece['seconds']:.3f}",
            "-i",
            str(still),
            "-an",
            "-vf",
            "scale=out_range=tv,format=yuv420p",
            *ENCODE,
            str(out),
        ]
    )


def chapters(timeline: dict, pieces: list[dict], total: float) -> list[tuple[float, str]]:
    found = [(to_output(c["t"], pieces), c["title"]) for c in timeline.get("chapters", [])]
    if found:
        found[0] = (0.0, FIRST_CHAPTER)
    return [(t, title) for t, title in found if t < total]


def write_metadata(path: Path, marks: list[tuple[float, str]], total: float) -> None:
    lines = [";FFMETADATA1", "title=DiAGRI: a complete research round (local demo)"]
    for index, (start, title) in enumerate(marks):
        end = marks[index + 1][0] if index + 1 < len(marks) else total
        lines += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={int(start * 1000)}",
            f"END={int(end * 1000)}",
            f"title={title}",
        ]
    path.write_text("\n".join(lines) + "\n")


def stamp(seconds: float) -> str:
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


def describe(piece: dict) -> str:
    if piece["kind"] == "hold":
        return f"hold  {piece['t']:7.1f} s for {piece['seconds']} s  {piece['label']}"
    return f"play  {piece['start']:7.1f}-{piece['end']:7.1f} s  x{piece['speed']:5.2f}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "folder", type=Path, help="the recorder's output folder (raw.mp4, timeline.json)"
    )
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--out", type=Path, required=True, help="final MP4 path")
    parser.add_argument(
        "--holds", type=Path, help="JSON list of {t, seconds, label} in raw seconds"
    )
    args = parser.parse_args()

    timeline = json.loads((args.folder / "timeline.json").read_text())
    raw = args.folder / "raw.mp4"
    holds = json.loads(args.holds.read_text()) if args.holds else []
    pieces = insert_holds(plan(timeline), holds)
    work = args.folder / "segments"
    work.mkdir(exist_ok=True)
    listing = []
    for index, piece in enumerate(pieces):
        out = work / f"seg_{index:02d}.mp4"
        (encode_hold if piece["kind"] == "hold" else encode_play)(args.ffmpeg, raw, piece, out)
        listing.append(f"file '{out.resolve()}'")
        print(f"piece {index:2d}: {describe(piece)}")
    concat = args.folder / "concat.txt"
    concat.write_text("\n".join(listing) + "\n")

    total = sum(length(piece) for piece in pieces)
    marks = chapters(timeline, pieces, total)
    meta = args.folder / "chapters.ffmeta"
    write_metadata(meta, marks, total)
    run(
        [
            args.ffmpeg,
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat),
            "-i",
            str(meta),
            "-map",
            "0:v",
            "-map_metadata",
            "1",
            "-map_chapters",
            "1",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(args.out),
        ]
    )
    text = "\n".join(f"{stamp(t)}  {title}" for t, title in marks)
    (args.folder / "chapters.txt").write_text(text + "\n")
    print(f"final: {args.out} ({stamp(total)}, raw {stamp(timeline['duration'])})")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
