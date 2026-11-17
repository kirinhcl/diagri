# Recording a DiAGRI demo video

These scripts record a complete research round on the development workbench as a narrated
1080p video: sign-in, a project and protocol, a question to the agents, the planner's run sheet,
review and approval, a fast-forwarded 21-day stage, the researcher's analysis and the published
report. They were used for `DiAGRI-full-round-demo-2026-11-17.mp4` (6:27, recorded on
17 November 2026).

Everything runs locally against `scripts/dev_workbench.py` and the simulated AC5. Nothing here
changes the platform: the launcher only lengthens sign-in sessions for the recording.

## What the viewer should be told

- The tent, the plants and the sensors are simulated. The canopy values are a seeded growth
  curve from `onsite_helper.py`, not lettuce data.
- The manual tasks (watering, photo, canopy measurement) are recorded by `onsite_helper.py`,
  standing in for the person on site: under `--fast-forward` a task is open for about 1.3 real
  seconds, too short to click on camera. Its notes and each measurement's `method` say so, and
  so does a subtitle in the video.
- Segments marked **⏩ TIME-LAPSE** are sped up (the waits for the model roles and the stage).
  Freeze-frame holds are added in the edit where there is text to read.

## What you need

- The project's `.venv` and the Claude Code CLI signed in (`claude auth status`); the model roles
  run through it, as in [the example round](../../docs/wiki/en/Example-Full-Round-With-Claude.md).
  A recording makes about 15 to 20 model calls.
- Node.js and Playwright with Chromium. The repository has no `package.json`, so install it
  somewhere and point `PW_PATH` at the package:
  `npm install --prefix ~/pw playwright && npx --prefix ~/pw playwright install chromium`,
  then `export PW_PATH=~/pw/node_modules/playwright`.
- An ffmpeg with libx264. One way: `python3 -m venv ~/ffvenv && ~/ffvenv/bin/pip install
  imageio-ffmpeg`, then
  `export FFMPEG=$(~/ffvenv/bin/python -c "import imageio_ffmpeg as f; print(f.get_ffmpeg_exe())")`.
- Port 8770 free, and `GROWBRIDGE_DEV_SECRET` set (at least 12 characters). Every script reads
  the dev operator's secret from that variable.

Output goes to `$DEMO_OUT` (default `<system temp>/diagri-demo`), never into the repository.

## 1. Rehearse

Run the operator's steps against a seeded instance (no model roles) to check every selector
before spending model calls. A fresh data directory gets a stage waiting for review
(`stage-dev`), which the rehearsal approves and starts.

```sh
export GROWBRIDGE_DEV_SECRET='at least twelve characters'
.venv/bin/python scripts/demo/launch_workbench.py --data-dir /tmp/diagri-rehearse
# in a second terminal:
node scripts/demo/demo.cjs rehearse
```

Every write is checked through the API (protocol saved, budget set, message accepted, stage
started); a refused request stops the run with `DEMO ERROR` and a `failure.png`. Stop the
workbench afterwards; a rehearsed data directory cannot be rehearsed again.

## 2. Record

```sh
unset ANTHROPIC_BASE_URL ANTHROPIC_API_KEY      # Claude Code uses its own sign-in
DEMO_CLEAN_SEED=1 .venv/bin/python scripts/demo/launch_workbench.py --claude-code \
  --fast-forward --data-dir /tmp/diagri-record --transcript /tmp/diagri-record.jsonl
# second terminal: the person on site
.venv/bin/python scripts/demo/onsite_helper.py --log /tmp/diagri-helper.jsonl
# third terminal: the recording (about 15 minutes)
node scripts/demo/demo.cjs record
```

`DEMO_CLEAN_SEED=1` approves the safety limits but seeds no project, so the inbox shows only the
project made on camera. The recorder waits on real state, not on timers: a reply in the
conversation, a stage in `pending_review`, the stage ended, the round `delivered`, and all model
tasks idle for 10 seconds. It writes `raw.mp4` (1920×1080, 25 fps) and `timeline.json` (the
time-lapse segments and chapters, in seconds of the raw video).

## 3. Edit

Find still moments where the text is worth reading, list them as holds, and render:

```sh
python3 scripts/demo/find_stills.py "$DEMO_OUT/record/raw.mp4" --ffmpeg "$FFMPEG" 150-180 820-850
python3 scripts/demo/edit.py "$DEMO_OUT/record" --ffmpeg "$FFMPEG" \
  --holds my-holds.json --out DiAGRI-demo.mp4
```

A holds file is a list of `{"t": <raw seconds>, "seconds": <length>, "label": "..."}`. The times
belong to one recording: `holds-2026-11-17.json` is the list used for the 17 November video and
only shows the format. A hold inside a time-lapse is refused. The editor writes the final MP4
with embedded chapters and a `chapters.txt`.

## Files

| File | Role |
| --- | --- |
| `launch_workbench.py` | Runs `dev_workbench.py` with sessions that outlive the fast-forwarded clock; `DEMO_CLEAN_SEED=1` seeds only the safety limits |
| `onsite_helper.py` | Records each manual task as it falls due, and one canopy value per plant for each measurement task |
| `demo.cjs` | Browser helpers (cursor, subtitles, chapter cards, API checks) and the runner |
| `scenes.cjs` | The story, scene by scene |
| `screencast.cjs` | Records the page through the DevTools screencast at device pixels, encoded live with libx264 |
| `edit.py` | Speeds up the time-lapse segments, cuts, adds holds, embeds chapters |
| `find_stills.py` | Lists still intervals, to choose the holds |
| `discover.cjs` | Dumps each page's controls and a screenshot, for writing new scenes |

The tests are in `tests/test_demo_tools.py`.

## Things that bit the first recording

- The workbench sends `style-src 'self'`, which blocks the injected overlay; the recording
  browser bypasses CSP (only that browser).
- The budget form needs both the call limit and the cost; with one empty the browser refuses
  the submit silently, and the next question to the agents is refused with `budget`.
- Starting a round opens the round page, so the budget is set before it.
- Approving more than 300 seconds after sign-in brings up the re-authentication dialog; the
  recorder types the secret into it, and the video shows it.
- Playwright's own video recorder captures CSS pixels and encodes VP8 at about 1 Mbit/s, which
  leaves a 1440×810 page small and blurred inside a 1080p frame; hence `screencast.cjs`.
- Since the console's third usability batch the protocol is entered through its form (the JSON
  editor under "Advanced (JSON)" starts empty), so the scene types the question and fills the
  other fields inside a time-lapse. "Start stage" now asks first; `handleDialogs` confirms that
  question the same way it answers the re-authentication dialog.
