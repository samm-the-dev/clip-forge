# Clip Forge

A Python CLI tool for automating video-to-WebP clip creation with DaVinci Resolve.

## Workflow

1. **Search** — Point at your media library, describe the moment you're looking for
2. **Find** — Subtitles are extracted and searched to locate the timestamp
3. **Cut** — FFmpeg rough-cuts the segment with configurable padding
4. **Project** — A DaVinci Resolve project is created with the clip on the timeline, subtitle text on a subtitle track, and WebP render settings preconfigured
5. **Refine** — Open Resolve, fine-tune the cut, style subtitles, and export

## Setup

### Requirements

- Python 3.10+
- FFmpeg (on PATH or configured in `config.json`)
- DaVinci Resolve (running when creating projects)
- `pysrt` library: `pip install pysrt`
- `obsws-python` library (for capture sessions): `pip install obsws-python`
- OBS Studio 28+ with WebSocket server enabled (Tools > WebSocket Server Settings)

### Configuration

Copy `config.example.json` to `config.json` and set your paths:

```json
{
  "media_paths": {
    "movies": "D:/Movies",
    "shows": "D:/TV Shows"
  },
  "output_dir": "D:/ClipForge",
  "ffmpeg_path": "ffmpeg",
  "padding_seconds": 3,
  "default_fps": 15,
  "default_width": 480
}
```

### Usage

```bash
# === Local file workflow (subtitle search) ===

# Search for a moment
python clip_forge.py search "severance" "Mark says please try to enjoy"

# Cut the clip once you've confirmed the timestamps
python clip_forge.py cut "D:/TV Shows/Severance/S02E04.mkv" --start 00:23:15 --end 00:23:22

# Create a Resolve project from the cut clip
python clip_forge.py resolve "D:/ClipForge/clips/severance_s02e04_clip.mkv" --property "Severance"

# Full pipeline: search + cut + resolve project
python clip_forge.py auto "severance s02e04" "Mark says please try to enjoy"

# === OBS capture session workflow ===

# Start an interactive capture session
python clip_forge.py session "Severance" --episode S02E04

# Session commands (at the clip> prompt):
#   capture          — start recording
#   capture <note>   — start recording with a note
#   stop             — stop recording
#   stop <subtitle>  — stop recording and attach subtitle text
#   episode S02E05   — mark episode change
#   status           — show session status
#   pause / resume   — pause/resume recording
#   done             — end session and create Resolve projects

# === Subtitle styles ===

# List all configured property styles
python clip_forge.py styles

# Update a property's subtitle style
python clip_forge.py styles update --property "Severance"
```

## Workflows

### Local Files (subtitle search)

For media files you already have with embedded subtitles:

1. You: "Find the scene in Severance S2E4 where Mark says 'please try to enjoy each sandwich'"
2. Claude runs the search, shows matching subtitle lines with timestamps
3. You confirm or adjust the range
4. Claude runs the cut and Resolve project setup
5. You open Resolve and refine

### OBS Capture Sessions

For capturing from YouTube, streaming services, etc. via Firefox + OBS:

1. Open OBS and Firefox on your main monitor
2. Start a session: `python clip_forge.py session "Severance" --episode S02E04`
3. The tool connects to OBS, sets up the output directory, and checks your subtitle style
4. Watch on the main monitor. When a moment hits, type `capture` on the side monitor
5. Type `stop` when done (optionally with subtitle text: `stop "Please try to enjoy each sandwich"`)
6. Mark episode changes mid-session: `episode S02E05`
7. Type `done` to end — all clips get Resolve projects with your property's subtitle style
