"""Demo helper: stands in for the person on site while a stage is fast-forwarded.

Under --fast-forward a manual task is open for about 1.3 real seconds, too short to click in the
recorded browser. This helper signs in as the dev operator, watches every running stage, and
records each manual-task occurrence as done when it falls due:

- irrigation: recorded as watered by hand (a planned pump run waits real seconds while the
  development clock jumps, so it is not run under fast-forward; see the wiki's open points);
- photo: recorded as done;
- measurement: recorded as done, plus one canopy_area_growth value per plant, dated at the
  occurrence, so the frozen data window really holds the planned daily measurements.

Every note and every measurement's ``method`` says the values come from this simulation. The
plants are simulated; the values are a seeded growth curve, not lettuce data.
"""

import argparse
import http.cookiejar
import json
import math
import os
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://localhost:8770"
SECRET_VARIABLE = "GROWBRIDGE_DEV_SECRET"  # the same secret dev_workbench.py signs `dev` in with
HEADERS = {"Origin": BASE, "X-GrowBridge-UI": "1", "Content-Type": "application/json"}
POLL_SECONDS = 0.2
STAGE_SCAN_SECONDS = 2.0
PLANTS = 6
SEED = 20261117
NOTE = "demo helper: simulated person on site"
WATER_NOTE = "watered by hand (demo helper; planned pump runs are not used under fast-forward)"
METHOD = "top-view image (simulated)"
METRIC = "canopy_area_growth"
UNIT = "cm2/day"
BATCH = "batch-1"
LAYOUT = "layout-1"
DAY_SECONDS = 86400.0


class Client:
    def __init__(self, secret: str):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.post("/wb/login", {"name": "dev", "secret": secret})

    def _send(self, request: urllib.request.Request) -> dict:
        try:
            with self.opener.open(request, timeout=30) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")[:300]
            message = f"{request.get_method()} {request.full_url}: {error.code} {detail}"
            raise RuntimeError(message) from error

    def get(self, path: str) -> dict:
        return self._send(urllib.request.Request(BASE + path))

    def post(self, path: str, body: dict) -> dict:
        data = json.dumps(body).encode()
        return self._send(urllib.request.Request(BASE + path, data=data, headers=HEADERS))


def running_stages(client: Client) -> list[str]:
    stages = []
    for project in client.get("/wb/projects").get("projects", []):
        latest = project.get("latest_round") or {}
        round_id = latest.get("round_id")
        if not round_id:
            continue
        for stage in client.get(f"/wb/rounds/{round_id}").get("stages", []):
            if stage.get("state") == "running":
                stages.append(stage["stage_id"])
    return stages


def growth_value(rng: random.Random, plant_factor: float, day: float) -> float:
    """Daily canopy growth (cm2/day) of a young lettuce under 70 % light: rises with leaf area."""
    rate = 3.0 * math.exp(0.1 * day)
    return round(rate * plant_factor * rng.gauss(1.0, 0.05), 2)


def done_at_for(due_at: float, now: float) -> float:
    """When a task counts as done: its due time once due, else now (the server accepts up to an
    hour early and never a time in the future)."""
    return due_at if now >= due_at else now


class Helper:
    def __init__(self, client: Client, log: Path):
        self.client = client
        self.log = log
        self.rng = random.Random(SEED)
        self.plant_factors = [self.rng.gauss(1.0, 0.07) for _ in range(PLANTS)]
        self.stage_info: dict[str, dict] = {}
        self.handled: set[tuple[str, str, float]] = set()

    def write(self, line: dict) -> None:
        with self.log.open("a") as handle:
            handle.write(json.dumps(line) + "\n")

    def measure(self, stage_id: str, due_at: float) -> None:
        info = self.stage_info[stage_id]
        day = (due_at - (info.get("started_at") or due_at)) / DAY_SECONDS
        for index in range(PLANTS):
            body = {
                "experiment_id": info["experiment_id"],
                "batch": BATCH,
                "plant_id": f"plant-{index + 1}",
                "layout_version": LAYOUT,
                "measured_at": due_at,
                "position": f"tent-1/p{index + 1}",
                "method": METHOD,
                "metric": METRIC,
                "value": growth_value(self.rng, self.plant_factors[index], day),
                "unit": UNIT,
            }
            self.client.post("/wb/measurements", body)
        self.write({"stage": stage_id, "measured_at": due_at, "plants": PLANTS})

    def record(self, stage_id: str, item: dict, now: float) -> None:
        due_at = item["due_at"]
        done_at = done_at_for(due_at, now)
        kind = item.get("kind")
        note = WATER_NOTE if kind == "irrigation" else NOTE
        if kind == "measurement":
            self.measure(stage_id, due_at)
        body = {
            "task_id": item["task_id"],
            "due_at": due_at,
            "outcome": "done",
            "done_at": done_at,
            "note": note,
        }
        self.client.post(f"/wb/stages/{stage_id}/manual-tasks", body)
        self.write({"stage": stage_id, "task": item["task_id"], "kind": kind, "due_at": due_at})

    def step(self, stage_id: str) -> None:
        if stage_id not in self.stage_info:
            self.stage_info[stage_id] = self.client.get(f"/wb/stages/{stage_id}")
        listing = self.client.get(f"/wb/stages/{stage_id}/manual-tasks")
        now = listing["now"]
        for item in listing.get("occurrences", []):
            key = (stage_id, item["task_id"], item["due_at"])
            if key in self.handled or item.get("status") not in ("open", "late"):
                continue
            self.handled.add(key)
            try:
                self.record(stage_id, item, now)
            except RuntimeError as error:
                self.write({"stage": stage_id, "task": item["task_id"], "error": str(error)})
                print(f"helper: {error}", file=sys.stderr)

    def run(self) -> None:
        stages: list[str] = []
        scanned = 0.0
        while True:
            if time.monotonic() - scanned > STAGE_SCAN_SECONDS:
                stages = running_stages(self.client)
                scanned = time.monotonic()
            for stage_id in stages:
                try:
                    self.step(stage_id)
                except RuntimeError as error:
                    print(f"helper: {error}", file=sys.stderr)
            time.sleep(POLL_SECONDS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--log", type=Path, required=True, help="JSONL file, one line per record")
    args = parser.parse_args()
    secret = os.environ.get(SECRET_VARIABLE, "")
    if not secret:
        print(f"{SECRET_VARIABLE} must be set (the dev operator's secret)", file=sys.stderr)
        return 2
    client = Client(secret)
    print("helper: signed in; watching running stages", flush=True)
    try:
        Helper(client, args.log).run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
