"""Import clips into DaVinci Resolve via the scripting API.

Creates a project, imports MP4 clips, builds a trimmed timeline,
and generates an SRT file for manual subtitle import.

Requires:
    - DaVinci Resolve Studio running with a project open (or at project manager)
    - Python 3.8 (Resolve 20.x DLL is compiled against 3.8)
    - Run via: uv run --python 3.8 resolve_import.py <manifest> <clips_dir>

Usage:
    uv run --python 3.8 resolve_import.py <manifest.json> <clips_dir> --name ProjectName
"""

import argparse
import json
import os
import subprocess
import sys


def get_resolve():
    """Connect to DaVinci Resolve via the scripting API."""
    # Ensure DLL dependencies can be found
    resolve_dir = r"C:\Program Files\Blackmagic Design\DaVinci Resolve"
    os.add_dll_directory(resolve_dir)

    script_module_path = os.environ.get(
        "RESOLVE_SCRIPT_API",
        r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting",
    )
    modules_path = os.path.join(script_module_path, "Modules")
    if modules_path not in sys.path:
        sys.path.insert(0, modules_path)

    import DaVinciResolveScript as dvr

    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        print("ERROR: Could not connect to Resolve. Is it running?")
        sys.exit(1)
    return resolve


def get_clip_duration_seconds(clip_path: str) -> float:
    """Get clip duration in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1",
        clip_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        for line in result.stdout.splitlines():
            if line.startswith("duration="):
                return float(line.split("=")[1])
    except (subprocess.CalledProcessError, ValueError):
        pass
    return 0.0


def seconds_to_srt_timestamp(seconds: float) -> str:
    """Convert seconds to SRT timestamp format HH:MM:SS,mmm."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    ms = int((s - int(s)) * 1000)
    return f"{h:02d}:{m:02d}:{int(s):02d},{ms:03d}"


def build_srt(subtitle_timings: list) -> str:
    """Generate SRT content from subtitle timing data."""
    lines = []
    for i, sub in enumerate(subtitle_timings, 1):
        start_ts = seconds_to_srt_timestamp(sub["start_seconds"])
        end_ts = seconds_to_srt_timestamp(sub["end_seconds"])
        lines.append(f"{i}")
        lines.append(f"{start_ts} --> {end_ts}")
        lines.append(sub["text"])
        lines.append("")
    return "\n".join(lines)


def resolve_import(
    manifest_path: str,
    clips_dir: str,
    project_name: str = "ClipForge",
    fps: float = 23.976,
    width: int = 1920,
    height: int = 960,
    srt_output: str = None,
):
    """Import clips into Resolve and build a timeline.

    Args:
        manifest_path: Path to cut_manifest.json
        clips_dir: Directory containing MP4 clips
        project_name: Resolve project name
        fps: Timeline frame rate
        width: Timeline width
        height: Timeline height
        srt_output: Path for SRT file output (default: next to manifest)
    """
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # Collect clip info
    clips = []
    for entry in manifest:
        mp4_name = f"{entry['name']}.mp4"
        mp4_path = os.path.join(clips_dir, mp4_name)
        if not os.path.exists(mp4_path):
            print(f"  SKIP {entry['name']}: {mp4_name} not found")
            continue

        duration = get_clip_duration_seconds(mp4_path)
        if duration == 0:
            print(f"  SKIP {entry['name']}: could not determine duration")
            continue

        padding = entry.get("padding", 3)
        content_start = padding
        content_end = duration - padding
        content_start = max(0, min(content_start, duration - 0.1))
        content_end = max(content_start + 0.1, min(content_end, duration))
        content_duration = content_end - content_start

        clips.append({
            **entry,
            "mp4_path": os.path.abspath(mp4_path),
            "mp4_name": mp4_name,
            "total_duration": duration,
            "content_start": content_start,
            "content_end": content_end,
            "content_duration": content_duration,
        })

    if not clips:
        print("No clips found.")
        return

    print(f"Found {len(clips)} clips\n")

    # Connect to Resolve
    print("Connecting to Resolve...")
    resolve = get_resolve()
    print(f"  Connected: {resolve.GetProductName()} {resolve.GetVersionString()}")

    pm = resolve.GetProjectManager()

    # Create project
    project = pm.CreateProject(project_name)
    if not project:
        # Project might already exist — try loading it
        project = pm.LoadProject(project_name)
        if not project:
            print(f"ERROR: Could not create or load project '{project_name}'")
            return
        print(f"  Loaded existing project: {project_name}")
    else:
        print(f"  Created project: {project_name}")

    # Set project settings
    project.SetSetting("timelineFrameRate", str(fps))
    project.SetSetting("timelineResolutionWidth", str(width))
    project.SetSetting("timelineResolutionHeight", str(height))
    print(f"  Settings: {width}x{height} @ {fps}fps")

    # Import clips into media pool
    media_pool = project.GetMediaPool()
    clip_paths = [c["mp4_path"] for c in clips]

    print(f"\nImporting {len(clip_paths)} clips into media pool...")
    pool_items = media_pool.ImportMedia(clip_paths)
    if not pool_items:
        print("ERROR: Failed to import media")
        return
    print(f"  Imported {len(pool_items)} clips")

    # Map pool items by filename for matching
    pool_map = {}
    for item in pool_items:
        props = item.GetClipProperty()
        fname = props.get("File Name", "")
        pool_map[fname] = item

    # Build trimmed clip info list
    clip_infos = []
    ordered_clips = []
    for clip in clips:
        pool_item = pool_map.get(clip["mp4_name"])
        if not pool_item:
            print(f"  SKIP {clip['name']}: not found in media pool")
            continue

        in_frame = round(clip["content_start"] * fps)
        out_frame = round(clip["content_end"] * fps)

        clip_infos.append({
            "mediaPoolItem": pool_item,
            "startFrame": in_frame,
            "endFrame": out_frame,
        })
        ordered_clips.append(clip)

    # Create timeline from clips (appends back-to-back, trimmed)
    print(f"\nCreating timeline: {project_name} ({len(clip_infos)} clips)...")
    timeline = media_pool.CreateTimelineFromClips(project_name, clip_infos)
    if not timeline:
        print("ERROR: Failed to create timeline")
        return

    # Add subtitle track
    timeline.AddTrack("subtitle")

    # Build subtitle timings based on actual timeline positions
    tl_items = timeline.GetItemListInTrack("video", 1)
    subtitle_timings = []
    for item, clip in zip(tl_items, ordered_clips):
        if clip.get("subtitle") and not clip.get("is_action"):
            start_frame = item.GetStart()
            end_frame = item.GetEnd()
            subtitle_timings.append({
                "name": clip["name"],
                "text": clip["subtitle"],
                "start_seconds": start_frame / fps,
                "end_seconds": end_frame / fps,
            })

    # Write and import SRT
    if subtitle_timings:
        srt_path = srt_output or os.path.join(
            os.path.dirname(manifest_path), f"{project_name}.srt"
        )
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(build_srt(subtitle_timings))
        print(f"  SRT: {srt_path} ({len(subtitle_timings)} subtitles)")

        print("  -> Drag SRT onto the subtitle track, then apply preset")

    # Switch to Edit page
    resolve.OpenPage("edit")

    print(f"\nDone! Project '{project_name}' ready in Resolve.")


def main():
    parser = argparse.ArgumentParser(
        description="Import clips into DaVinci Resolve via scripting API"
    )
    parser.add_argument("manifest", help="Path to cut_manifest.json")
    parser.add_argument("clips_dir", help="Directory containing MP4 clips")
    parser.add_argument("--name", default="ClipForge", help="Project/timeline name")
    parser.add_argument("--fps", type=float, default=23.976, help="Frame rate")
    parser.add_argument("--width", type=int, default=1920, help="Timeline width")
    parser.add_argument("--height", type=int, default=960, help="Timeline height")
    parser.add_argument("--srt", help="Output SRT path")
    args = parser.parse_args()

    resolve_import(
        args.manifest,
        args.clips_dir,
        project_name=args.name,
        fps=args.fps,
        width=args.width,
        height=args.height,
        srt_output=args.srt,
    )


if __name__ == "__main__":
    main()
