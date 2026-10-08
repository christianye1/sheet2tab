# Sheet2Tab (MVP)

Take a photo of printed sheet music on your iPhone and get back guitar tab.

```
iPhone app ──JPEG──▶ FastAPI backend ──▶ oemer (OMR) ──▶ MusicXML ──▶ music21 ──▶ fingering ──▶ ASCII tab
```

```
backend/
  app/
    main.py          FastAPI app: POST /convert, POST /jobs, GET /jobs/{id}, GET /health
    jobs.py          background jobs with per-step progress
    config.py        host/port/timeouts (env vars)
    omr.py           image preprocessing + oemer subprocess
    parser.py        MusicXML -> NoteEvents (octave handling, range shifting)
    guitar.py        tuning, Position/NoteEvent types, candidate positions
    fingering.py     FingeringStrategy interface + LowestFretStrategy (placeholder)
    tab_renderer.py  6-line ASCII tab
    pipeline.py      glue: musicxml_to_tab(), image_to_tab()
  samples/ode_to_joy.musicxml
  scripts/convert_file.py   run the pipeline from the command line
  tests/
ios/
  Sheet2Tab.xcodeproj
  Sheet2Tab/         SwiftUI sources
```

## 1. Backend setup

Requires Python **3.11** (oemer's dependencies don't support 3.13+ yet). With
[uv](https://docs.astral.sh/uv/):

```bash
cd backend
uv venv -p 3.11 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

Or with plain pip: `python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt`.

Version pins in `requirements.txt` exist for a reason: oemer 0.1.8+ depends on
`onnxruntime-gpu` (no macOS wheels), and oemer uses `np.int`, which NumPy 1.24 removed.

The first OMR run downloads oemer's model checkpoints (a few hundred MB) into
the venv.

### Run the tests

```bash
.venv/bin/python -m pytest
```

### Try the pipeline without the phone or server

```bash
.venv/bin/python scripts/convert_file.py samples/ode_to_joy.musicxml
.venv/bin/python scripts/convert_file.py samples/ode_to_joy.musicxml --json
.venv/bin/python scripts/convert_file.py ~/Desktop/some_sheet_photo.jpg   # full OMR, takes minutes
```

### Run the server

```bash
.venv/bin/python -m app.main
```

It listens on `0.0.0.0:8000`, so other devices on your Wi-Fi can reach it. Settings
are environment variables:

| Variable | Default | |
|---|---|---|
| `SHEET2TAB_HOST` | `0.0.0.0` | bind address |
| `SHEET2TAB_PORT` | `8000` | port |
| `SHEET2TAB_OMR_TIMEOUT` | `600` | seconds before OMR is aborted |
| `SHEET2TAB_OMR_MAX_SIDE` | `2500` | images are downscaled to this many pixels on their longest side |
| `SHEET2TAB_MAX_UPLOAD_MB` | `20` | upload size limit |
| `SHEET2TAB_OMR_FAILURE_DIR` | `backend/.omr_failures` | failed OMR inputs + oemer output are saved here; empty string disables |
| `SHEET2TAB_OMR_CACHE_DIR` | `backend/.omr_cache` | OMR results are cached here by image hash; empty string disables |

Check it from the Mac:

```bash
curl http://localhost:8000/health
curl -F "file=@samples/ode_to_joy.musicxml" http://localhost:8000/convert   # MusicXML upload skips OMR
curl -F "file=@photo.jpg" http://localhost:8000/convert
```

Both endpoints take an optional form field `instrument`: `guitar` (default) or `piano`.
Piano mode reads both staves (the bottom two on piano-vocal sheets) as right and left hand,
skips the guitar steps, and returns note names per hand instead of tab:

```bash
curl -F "file=@samples/ode_to_joy.musicxml" -F instrument=piano http://localhost:8000/convert
```

`POST /jobs` also takes several `file` fields: consecutive pages of one piece, converted
into one result (each page through OMR on its own and cached on its own; page 2 starts where
page 1 ends; a page that fails is skipped with a warning). At most 20 pages
(`SHEET2TAB_MAX_PAGES`). The app sends every page of a PDF or a multi-page scan.

The app uses `POST /jobs` instead: it returns a job ID right away, and `GET /jobs/{id}`
reports the current step, overall progress, how long each step took, and finally the result.

Interactive API docs are at http://localhost:8000/docs.

## 2. Find your Mac's local IP

```bash
ipconfig getifaddr en0
```

(`en0` is Wi-Fi on most Macs; try `en1` if that prints nothing.) Alternatively:
System Settings → Wi-Fi → Details → IP address. The backend URL for the app is then
e.g. `http://192.168.1.20:8000`.

If the phone can't connect, macOS may be blocking it: the first time you start the server, allow
incoming connections for Python when prompted, or check System Settings → Network → Firewall.
Both devices must be on the same Wi-Fi network (guest networks often isolate devices).

## 3. Run the app on your iPhone

1. If you haven't already, accept the Xcode license once: `sudo xcodebuild -license`
   (and, if `xcodebuild` complains about Command Line Tools, run
   `sudo xcode-select -s /Applications/Xcode.app`).
2. Open `ios/Sheet2Tab.xcodeproj` in Xcode.
3. Select the **Sheet2Tab** target → **Signing & Capabilities** → choose your Team
   (a free Apple ID works). If Xcode says the bundle ID is taken, change
   `com.example.sheet2tab` to something unique.
4. Connect your iPhone by cable (or pair it over Wi-Fi), select it as the run
   destination, and press ⌘R.
5. On the phone, enable **Developer Mode** if asked (Settings → Privacy & Security),
   and trust the developer certificate (Settings → General → VPN & Device Management).
6. In the app, tap ⚙︎, enter the backend URL from step 2, and tap **Test connection**.
   Allow local network access when iOS asks.
7. Tap **Scan**, frame the page (the scanner finds its edges; drag the corners if needed), then tap **Convert to Tab**.

## Saving tabs

On the result screen, tap **Save**. The name is pre-filled with the title the phone read
from the photo (Apple Vision OCR: the largest text near the top of the page). Correct it
if it's wrong, pick a folder or create one, and save. The **Library** tab lists saved tabs.
Long-press or swipe an item to rename, move or delete it.

Each tab is a JSON file and each folder is a real folder in the app's Documents directory:

- They survive app updates and re-installs from Xcode. They're lost only if you delete the
  app, or change the bundle ID (which makes it a different app to iOS).
- They're part of iPhone/iCloud backups and appear in the Files app under
  *On My iPhone › Sheet2Tab*, so you can copy them off the phone.

## How it works / MVP limitations

- **OMR** is oemer. It's slow on a CPU (roughly 1–4 minutes per page on a laptop) and
  makes mistakes; the app keeps the screen awake and waits up to 15 minutes. If oemer
  proves too unreliable, the fallback is Audiveris (not integrated yet).
- **Parts:** only the first part/staff is converted (for piano music, that's the
  right hand); a warning says so.
- **Octaves:** guitar scores (treble clef with an 8 below, or a guitar instrument or title)
  are transposed down an octave to sounding pitch. Any note outside E2–C6 is shifted by
  octaves into range, with a warning.
- **Fingering:** `HandPositionStrategy` keeps the fretting hand compact and still. Each
  candidate fingering of a note or chord is scored for spread (distance of its fretted notes
  from their average fret), stretch (a large penalty beyond 4 frets) and height (a small
  preference for low frets); moving the hand between notes costs the distance between their
  average frets, and open strings don't move the hand. The cheapest sequence over the whole
  piece is found with dynamic programming. Notes that can't be placed at all are dropped
  with a warning. The weights are constructor arguments; `LowestFretStrategy` (lowest fret
  per note) is kept for comparison. Pass either to `musicxml_to_tab(..., strategy=...)`.
- **OMR timing:** oemer writes each staff's notes in the right order but positions them with
  unreliable `<backup>`s and filler rests, so `app/omr_cleanup.py` lays them out one after
  another per staff before parsing. Rests oemer didn't recognize are lost, so the notes
  after them come early within that measure.
- **Tab:** standard 6 lines, high e on top, `|` between measures, wrapped at 80
  columns. Spacing roughly follows note duration; tied notes are not re-struck.
