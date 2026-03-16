---
name: clip-forge
description: Extract video clips from movies/shows into animated WebPs with burned-in subtitles via DaVinci Resolve
user-invocable: true
argument-hint: "[project-name]"
allowed-tools:
  - Bash(python *)
  - Bash(uv *)
  - Bash(ffmpeg *)
  - Bash(ffprobe *)
  - Bash(powershell *)
  - Bash(start *)
  - Bash(ls *)
  - Bash(rm *)
  - Bash(mkdir *)
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Agent
---

# Clip Forge

Extract video clips from movies or TV shows, import into DaVinci Resolve for subtitle styling, and export as animated WebPs.

## Arguments

`$ARGUMENTS` should be a project name (e.g., "Frankenstein", "one-piece"). Creates `c:\Dev\clip-forge\projects/<name>/` if it doesn't exist.

## Config

Load config from `c:\Dev\clip-forge\config.json`:
- `media_paths.movies` — movie library root (e.g., `D:/Movies`)
- `media_paths.shows` — TV show library root (e.g., `D:/Shows`)
- `ffmpeg_path` — ffmpeg binary
- `subtitles.property_styles` — per-project subtitle font/color settings

## Pipeline Overview

```
Keep note → parse clips → find media → search subtitles → build manifest
  → cut clips → convert to MP4 → import to Resolve → manual editing
  → export WebPs via Resolve API
```

## Phase 0: Project Setup

1. Create the project directory if needed:
   ```bash
   mkdir -p "c:/Dev/clip-forge/projects/$ARGUMENTS/clips"
   ```

2. Ask the user: **Is this a movie or a TV show?**
   - Movie: single source file, timestamps are absolute
   - TV show: multiple episodes, timestamps prefixed with episode number

3. Load config:
   ```bash
   python -c "import json; print(json.dumps(json.load(open('c:/Dev/clip-forge/config.json')), indent=2))"
   ```

## Phase 1: Parse Clip Notes

The user provides clip notes as either:
- A **screenshot** of a Keep note (use vision to OCR)
- **Raw text** pasted into chat
- A path to an existing `clips.txt`

### Parsing Rules

Notes use shorthand timestamps. Common patterns:
- `19` or `19-` = 19:00 (19 minutes). The `-` means "slightly before"
- `58+` = ~58:00. The `+` means "slightly after"
- `202` = 2:02:00 (2 hours 2 minutes) — NOT 202 minutes
- `ep3 45:00` = episode 3 at 45 minutes (TV shows only)
- Quoted text = dialogue to search for in subtitles
- Unquoted descriptive text = clip name / action description
- `[action]` tag or no quotes = action clip (no subtitle, use timestamp directly)

### For TV Shows

Write `clips.txt` in the format `build_manifest.py` expects:
```
# Show Name — clip list
ep1 54:00 "I'll be the hero"
ep2 30:00 [action] ricochet_shot
```

### For Movies

Don't write clips.txt — build the manifest directly in Phase 2.

### Decision Gate

Show the parsed clip list to the user. Ask them to confirm, edit, or add clips before proceeding.

## Phase 2: Build Manifest

### TV Shows

Run `build_manifest.py`:
```bash
python c:/Dev/clip-forge/build_manifest.py projects/<name>/clips.txt <media_dir> projects/<name>/ --output projects/<name>/cut_manifest.json
```

This handles episode file finding, subtitle extraction/caching, and fuzzy search automatically.

### Movies

Build `cut_manifest.json` directly. Steps:

1. **Find the movie file.** Search the movies directory:
   ```bash
   python -c "
   from media_scanner import find_media
   from config_loader import load_config
   config = load_config()
   results = find_media('<movie name>', config['media_paths'])
   for r in results[:5]:
       print(r['path'])
   "
   ```
   Or use glob/ls on `D:/Movies/` to find it. Movie files are usually in a subdirectory named like `Movie Name (Year) [quality]/`.

2. **Find subtitles.** Look for:
   - External SRT in a `Subs/` subdirectory (common in YTS downloads): `Subs/English.srt`
   - External SRT next to the movie file: `*.srt`
   - Embedded subtitles: use `ffprobe` to check, extract with `subtitle_search.py`

3. **Search subtitles** for each dialogue clip. Use grep or the subtitle_search module:
   ```bash
   grep -in "search phrase" "<srt_path>"
   ```
   Then read surrounding lines to get the exact SRT timestamp.

4. **Write `cut_manifest.json`** with this schema:
   ```json
   [
     {
       "name": "slug_name",
       "subtitle": "Exact subtitle text from SRT",
       "start": 1234.567,
       "end": 1238.901,
       "padding": 3,
       "is_action": false,
       "source": "D:/Movies/Movie Name/file.mp4",
       "output": "c:/Dev/clip-forge/projects/<name>/clips/slug_name.mkv"
     }
   ]
   ```

   - `start`/`end` are in seconds (from SRT timestamps)
   - `padding` is added by batch_cut (default 3s each side)
   - Action clips have `"is_action": true` and empty `"subtitle"`
   - Slug names from dialogue: lowercase, underscores, max 60 chars

### Decision Gate

Show the manifest entries (clip name, timestamps, matched subtitle text). Ask user to confirm.

## Phase 3: Cut and Convert

Run from the `c:\Dev\clip-forge\` directory:

```bash
python batch_cut.py projects/<name>/cut_manifest.json
```

Then convert with auto-crop detection:

```bash
python batch_convert.py projects/<name>/cut_manifest.json --crop auto
```

Report: number of clips, file sizes, detected crop values. No decision gate needed.

## Phase 4: Import to Resolve

**Requires:** DaVinci Resolve Studio running. Python 3.8 via uv.

### Resolve API Setup

All Resolve API calls must go through a PowerShell wrapper script because:
- The `fusionscript.dll` is compiled against Python 3.8 ABI
- Environment variables with `$` need PowerShell (not bash inline)

Write a `.ps1` file in the project directory, then run it:

```powershell
$env:RESOLVE_SCRIPT_LIB = "C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll"
$env:RESOLVE_SCRIPT_API = "C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting"
$env:PYTHONPATH = "C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules"

$uv = "C:\Users\smars\AppData\Roaming\Python\Python313\Scripts\uv.exe"
& $uv run --python 3.8 -- python <script.py> <args>
```

### Import Command

Probe the first MP4 clip to get the resolution after cropping:
```bash
ffprobe -v quiet -show_entries stream=width,height -of default=noprint_wrappers=1 "projects/<name>/clips/<first_clip>.mp4"
```

Then write and run the import script:
```powershell
& $uv run --python 3.8 -- python "c:\Dev\clip-forge\resolve_import.py" "c:\Dev\clip-forge\projects\<name>\cut_manifest.json" "c:\Dev\clip-forge\projects\<name>\clips" --name "<ProjectName>" --fps 23.976 --width <w> --height <h>
```

### Manual Editing Instructions

After import, tell the user:
1. Drag the SRT file onto the subtitle track: `c:\Dev\clip-forge\projects\<name>\<ProjectName>.srt`
2. Apply the font preset (check `config.json` `subtitles.property_styles` for this project, or ask the user)
3. Select all clips, Insert Gap between each (user's keybind)
4. Trim/remove any clips as needed
5. Tell Claude when done

### Decision Gate

Wait for user to confirm they've finished manual editing before proceeding to export.

## Phase 4b: Revising Clips (Post-Import)

When the user reviews clips in Resolve and requests adjustments (wrong action, extend/shorten, missed line, audio issues), handle them as a batch:

### Workflow

1. **Collect all requested changes** before cutting anything.

2. **Look up subtitle context** for each clip using the cached SRT:
   ```bash
   python -c "
   import json
   subs = json.load(open('projects/<name>/subs_cache/ep0N.json'))
   for s in subs:
       if <t1> <= s['start_seconds'] <= <t2>:
           print(f\"{s['start_seconds']:.3f}-{s['end_seconds']:.3f}: {s['text']}\")
   "
   ```
   Use this to find adjacent lines (extend to include a line, find where an action actually is, etc.).

3. **Write a mini-manifest** (e.g., `recut_manifest.json`) with only the revised clips. Adjust `start`/`end` directly — keep `padding: 3` unless doing something unusual.

4. **Cut and convert:**
   ```bash
   python batch_cut.py projects/<name>/recut_manifest.json
   python batch_convert.py projects/<name>/recut_manifest.json --crop auto
   ```

5. **Append to existing Resolve timeline** using `resolve_append.py` (at `c:/Dev/clip-forge/resolve_append.py`):
   ```powershell
   & $uv run --python 3.8 -- python "c:\Dev\clip-forge\resolve_append.py" \
     "c:\Dev\clip-forge\projects\<name>\recut_manifest.json" \
     "c:\Dev\clip-forge\projects\<name>\clips" \
     --project "<ProjectName>" --fps 23.976
   ```
   This loads the existing project, appends clips to the end of the current timeline, and writes `recut.srt` for the new dialogue clips. **IMPORTANT:** The manifest passed here must contain ONLY the clips being appended — not the full original manifest — or duplicates will land on the timeline.

6. **New SRT:** `recut.srt` is written to the project folder with timeline-offset timestamps. User drags it onto the subtitle track and applies the font preset.

### Notes

- **Overwriting files is fine** — batch_cut/batch_convert overwrite by name. Resolve may cache old versions; closing and reopening Resolve clears the cache.
- **Action clip timing:** If an action clip misses the right moment, search the subtitle cache for the nearest line (e.g., the character shouting the move name) and anchor the start there.
- **Extending in one direction only:** Just shift `start` or `end` in the manifest; `padding` handles the buffer on both sides automatically.
- **Dropped clips:** If the user removes a clip from scope mid-session, drop it from the recut manifest entirely.

## Phase 5: Export WebPs

Before running the export script, confirm these two Deliver settings are set (both are non-default):
- **Export Subtitle** → checked, format: **Burn into video**
- **Playback** → **Infinite Loops** checked

Write and run the export script via PowerShell:
```powershell
& $uv run --python 3.8 -- python "c:\Dev\clip-forge\resolve_export.py" "c:\Dev\clip-forge\projects\<name>\cut_manifest.json" --output "<output_dir>" --width 640
```

**Naming strategy:** After any revisions (recuts appended, clips reordered), the manifest's positional order no longer matches the timeline. Use clip filenames from the media pool instead — they're always correct. First inspect the timeline to get the true clip order:

```powershell
# inspect_timeline.ps1 — prints Position | Filename | Frames for every clip
& $uv run --python 3.8 -- python -c "
import os, sys
os.add_dll_directory(r'C:\Program Files\Blackmagic Design\DaVinci Resolve')
sys.path.insert(0, r'C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules')
import DaVinciResolveScript as dvr
resolve = dvr.scriptapp('Resolve')
project = resolve.GetProjectManager().GetCurrentProject()
timeline = project.GetCurrentTimeline()
clips = timeline.GetItemListInTrack('video', 1)
for i, clip in enumerate(clips, 1):
    props = clip.GetMediaPoolItem().GetClipProperty() if clip.GetMediaPoolItem() else {}
    fname = props.get('File Name', '(unknown)')
    print('%d | %s | %d frames' % (i, fname, clip.GetEnd() - clip.GetStart()))
"
```

Then build a name list from filenames (strip `.mp4`) and pass it to a custom export run, or re-export using `--auto-name` with the subtitle track if subtitles are correct. If the subtitle track is unreliable, do a fresh export using the filename-derived name list.

If the user removed clips in Resolve (fewer timeline clips than manifest entries), use `--auto-name` instead of a manifest to detect names from the subtitle track — but only if the subtitle track accurately reflects every clip.

The output directory is typically: `C:\Users\smars\OneDrive\Pictures\Movies & TV\<ProjectName>\`

### Decision Gate

Report file names and sizes. Ask the user to review. Offer to re-export individual clips:
```powershell
& $uv run --python 3.8 -- python "c:\Dev\clip-forge\resolve_export.py" --auto-name --output "<dir>" --name "<clip_name>"
```

## Key Files

| File | Purpose |
|------|---------|
| `build_manifest.py` | TV show manifest builder (episode subtitle search) |
| `batch_cut.py` | FFmpeg stream-copy cuts from manifest |
| `batch_convert.py` | Re-encode to MP4 with crop/stereo downmix |
| `resolve_import.py` | Create Resolve project + timeline (Python 3.8) |
| `resolve_export.py` | Export individual WebPs via Resolve API (Python 3.8) |
| `subtitle_search.py` | SRT parsing, fuzzy subtitle search |
| `detect_crop.py` | Letterbox crop detection |
| `media_scanner.py` | Media directory scanner, fuzzy file finder |
| `config_loader.py` | Config.json loader |
| `cutter.py` | Low-level FFmpeg cutting utilities |
