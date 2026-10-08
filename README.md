# Sheet2Tab (MVP)

Take a photo (or PDF) of printed sheet music on your iPhone and get back guitar tab or a
piano view of both hands, with playback to play along to.

```
iPhone app ──JPEG pages──▶ FastAPI backend ──▶ pre-checks ──▶ oemer (OMR) ──▶ MusicXML
   ──▶ timing cleanup ──▶ music21 ──▶ guitar: fingering + ASCII tab  |  piano: notes per hand
   ──▶ back to the app: text + note list ──▶ playback
```

```
backend/
  app/
    main.py          FastAPI app: POST /jobs, GET/DELETE /jobs/{id}, POST /convert, GET /health
    jobs.py          background jobs: per-step progress and timings, cancel
    config.py        host/port/timeouts/limits (env vars)
    omr.py           image preprocessing, OMR cache, oemer subprocess with streamed progress
    oemer_runner.py  runs the oemer CLI with a workaround for one of its crashes
    tab_detect.py    refuses sheets that already have 6-line TAB staffs
    omr_cleanup.py   fixes note timing in oemer's MusicXML
    parser.py        MusicXML -> note events (guitar) or notes per hand (piano)
    guitar.py        tuning, Position/NoteEvent types, candidate positions
    fingering.py     HandPositionStrategy (default) and LowestFretStrategy
    tab_renderer.py  6-line ASCII tab; piano note names per hand
    pipeline.py      glue: images_to_tab(), musicxml_pages_to_tab()
  samples/           test inputs (other sheet music in here stays local, see .gitignore)
  scripts/convert_file.py   run the pipeline from the command line
  tests/
ios/
  Sheet2Tab.xcodeproj
  Sheet2Tab/         SwiftUI sources, plus the GeneralUser GS SoundFont for playback
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

While working on the backend, this restarts the server whenever a file in `app/` changes
(a restart drops conversions that are still running):

```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir app
```

It listens on `0.0.0.0:8000`, so other devices on your Wi-Fi can reach it. Settings
are environment variables:

| Variable | Default | |
|---|---|---|
| `SHEET2TAB_HOST` | `0.0.0.0` | bind address |
| `SHEET2TAB_PORT` | `8000` | port |
| `SHEET2TAB_OMR_TIMEOUT` | `600` | seconds before OMR of one page is aborted |
| `SHEET2TAB_OMR_MAX_SIDE` | `2500` | images are downscaled to this many pixels on their longest side |
| `SHEET2TAB_MAX_UPLOAD_MB` | `20` | size limit per uploaded file |
| `SHEET2TAB_MAX_PAGES` | `20` | pages per conversion |
| `SHEET2TAB_OMR_CACHE_DIR` | `backend/.omr_cache` | OMR results are cached here by image hash; empty string disables |
| `SHEET2TAB_OMR_FAILURE_DIR` | `backend/.omr_failures` | failed OMR inputs + oemer output are saved here; empty string disables |

### API

The app uses background jobs, because OMR takes minutes per page:

| Endpoint | |
|---|---|
| `POST /jobs` | Upload one or more pages (`file` fields, in order) and an optional `instrument` (`guitar` or `piano`); returns a job ID at once |
| `GET /jobs/{id}` | Status, current step, overall progress, seconds per step, and the result when done |
| `DELETE /jobs/{id}` | Cancel; stops oemer within a fraction of a second |
| `POST /convert` | One file, synchronous: the request stays open until the result is ready |
| `GET /health` | Connection check |

Several pages are converted into one result: each page goes through OMR on its own (and is
cached on its own), page 2 starts where page 1 ends, and a page that fails is skipped with
a warning. Only one OMR runs at a time; other jobs wait as "queued".

Check it from the Mac:

```bash
curl http://localhost:8000/health
curl -F "file=@samples/ode_to_joy.musicxml" http://localhost:8000/convert   # MusicXML upload skips OMR
curl -F "file=@samples/ode_to_joy.musicxml" -F instrument=piano http://localhost:8000/convert
curl -F "file=@photo.jpg" http://localhost:8000/convert
```

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
Both devices must be on the same Wi-Fi network. Company, university and guest networks often
isolate devices; then turn on the iPhone's Personal Hotspot, connect the Mac to it, and use
the Mac's new IP.

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

In the iOS Simulator the scanner is unavailable (no camera); use `http://localhost:8000`
and add test images with `xcrun simctl addmedia booted <image>`.

## Using the app

1. Pick the sheet music:
   - **Scan**: Apple's document scanner finds the page edges and straightens the page; drag
     the corners if needed. All scanned pages are used.
   - **Library**: a photo; the page is detected and you can adjust its corners or use the
     whole photo.
   - **Files**: a PDF (all pages, rendered sharply) or an image.
2. Choose **Guitar** or **Piano** and tap **Convert to Tab**. The screen shows the current
   step, a progress bar and how long each step took. **Cancel** stops the server too.
3. The result shows the tab (guitar) or note names per hand (piano), plus warnings.
4. **Play** opens playback: for guitar, notes scroll along 6 string lanes toward a line
   where they are played; for piano, notes fall onto a keyboard (right hand blue, left
   orange). A note's length on screen is its duration. Tap to pause.

## Saving tabs

On the result screen, tap **Save**. The name is pre-filled with the title the phone read
from the photo (Apple Vision OCR: the largest text near the top of the page) or from the
PDF's text. Correct it if it's wrong, pick a folder or create one, and save. The **Library**
tab lists saved tabs. Long-press or swipe an item to rename, move or delete it.

Each tab is a JSON file and each folder is a real folder in the app's Documents directory:

- They survive app updates and re-installs from Xcode. They're lost only if you delete the
  app, or change the bundle ID (which makes it a different app to iOS).
- They're part of iPhone/iCloud backups and appear in the Files app under
  *On My iPhone › Sheet2Tab*, so you can copy them off the phone.

## How it works / MVP limitations

- **OMR** is oemer. It's slow on a CPU (about 3–5 minutes per page on a laptop; ~95% of that
  is its two neural networks) and makes mistakes, especially in rhythm. Its rule-based steps
  after the networks crash on some inputs; one crash is worked around in `oemer_runner.py`.
  Each failure is saved to `backend/.omr_failures/` for debugging.
- **Pre-checks:** a repeated image (same bytes) skips OMR via the cache. Sheets that already
  contain 6-line TAB staffs are refused, because they make oemer crash.
- **OMR timing:** oemer writes each staff's notes in the right order but positions them with
  unreliable `<backup>`s and filler rests, so `app/omr_cleanup.py` lays them out one after
  another per staff before parsing. Rests oemer didn't recognize are lost, so the notes
  after them come early within that measure.
- **Staves:** a *staff* is one set of five lines; piano music has two per line of music
  (right and left hand), piano-vocal sheets three. Guitar mode converts only the top staff,
  with a warning when there are more. Piano mode uses the bottom two as right and left hand.
- **Tempo:** from the score's metronome mark, else 90 BPM. oemer never supplies one (it
  doesn't read text), so OMR results always play at 90 BPM.
- **Octaves (guitar):** guitar scores (treble clef with an 8 below, or a guitar instrument or
  title) are transposed down an octave to sounding pitch. Any note outside E2–C6 is shifted
  by octaves into range, with a warning.
- **Fingering (guitar):** `HandPositionStrategy` keeps the fretting hand compact and still. Each
  candidate fingering of a note or chord is scored for spread (distance of its fretted notes
  from their average fret), stretch (a large penalty beyond 4 frets) and height (a small
  preference for low frets); moving the hand between notes costs the distance between their
  average frets, and open strings don't move the hand. The cheapest sequence over the whole
  piece is found with dynamic programming. Notes that can't be placed at all are dropped
  with a warning. The weights are constructor arguments; `LowestFretStrategy` (lowest fret
  per note) is kept for comparison. Pass either to `musicxml_to_tab(..., strategy=...)`.
- **Tab (guitar):** standard 6 lines, high e on top, `|` between measures, wrapped at 80
  columns. Spacing roughly follows note duration; tied notes are not re-struck.
- **Piano text:** note names per hand, one column per measure (`R |E4 F4|` / `L |C3+G3|`);
  tied notes become one long note.
- **Playback:** Apple's sequencer and sampler with the bundled GeneralUser GS SoundFont: jazz
  guitar (GM 26) and tine electric piano (GM 4). The acoustic guitar presets cut off after
  about 1 s in Apple's sampler, so they aren't used.

## Licenses

oemer and onnxruntime (MIT), music21 (BSD-3-Clause) and FastAPI (MIT) run on the backend.
The app bundles GeneralUser GS v2.0.3 by S. Christian Collins, whose license allows use in
software projects including commercial ones (`ios/Sheet2Tab/GeneralUser-GS-LICENSE.txt`).
