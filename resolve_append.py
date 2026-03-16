"""Append clips to an existing Resolve timeline and write a new SRT.

Usage:
    uv run --python 3.8 resolve_append.py <manifest.json> <clips_dir>
        --project ProjectName [--srt output.srt] [--fps 23.976]
"""

import argparse
import json
import os
import subprocess
import sys


def get_resolve():
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
        print("ERROR: Could not connect to Resolve.")
        sys.exit(1)
    return resolve


def get_clip_duration_seconds(clip_path):
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


def seconds_to_srt_timestamp(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    ms = int((s - int(s)) * 1000)
    return f"{h:02d}:{m:02d}:{int(s):02d},{ms:03d}"


def build_srt(subtitle_timings):
    lines = []
    for i, sub in enumerate(subtitle_timings, 1):
        lines.append(f"{i}")
        lines.append(f"{seconds_to_srt_timestamp(sub['start_seconds'])} --> {seconds_to_srt_timestamp(sub['end_seconds'])}")
        lines.append(sub["text"])
        lines.append("")
    return "\n".join(lines)


def resolve_append(manifest_path, clips_dir, project_name, fps=23.976, srt_output=None):
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

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
        content_start = max(0, min(padding, duration - 0.1))
        content_end = max(content_start + 0.1, min(duration - padding, duration))
        clips.append({
            **entry,
            "mp4_path": os.path.abspath(mp4_path),
            "mp4_name": mp4_name,
            "total_duration": duration,
            "content_start": content_start,
            "content_end": content_end,
        })

    if not clips:
        print("No clips found.")
        return

    print(f"Found {len(clips)} clips\n")

    resolve = get_resolve()
    print(f"  Connected: {resolve.GetProductName()} {resolve.GetVersionString()}")

    pm = resolve.GetProjectManager()
    project = pm.LoadProject(project_name)
    if not project:
        print(f"ERROR: Could not load project '{project_name}'")
        sys.exit(1)
    print(f"  Loaded project: {project_name}")

    media_pool = project.GetMediaPool()
    clip_paths = [c["mp4_path"] for c in clips]

    print(f"Importing {len(clip_paths)} clips into media pool...")
    pool_items = media_pool.ImportMedia(clip_paths)
    if not pool_items:
        print("ERROR: Failed to import media")
        sys.exit(1)
    print(f"  Imported {len(pool_items)} clips")

    pool_map = {}
    for item in pool_items:
        props = item.GetClipProperty()
        fname = props.get("File Name", "")
        pool_map[fname] = item

    # Get current timeline (first one)
    timeline = project.GetCurrentTimeline()
    if not timeline:
        tl_count = project.GetTimelineCount()
        if tl_count > 0:
            timeline = project.GetTimelineByIndex(1)
    if not timeline:
        print("ERROR: No timeline found in project. Run resolve_import.py first.")
        sys.exit(1)
    print(f"  Timeline: {timeline.GetName()}")

    # Get current end frame to calculate SRT offsets
    existing_items = timeline.GetItemListInTrack("video", 1)
    timeline_end_frame = 0
    if existing_items:
        last = existing_items[-1]
        timeline_end_frame = last.GetEnd()
    print(f"  Current timeline end: frame {timeline_end_frame} ({timeline_end_frame / fps:.1f}s)")

    # Build append list
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

    print(f"\nAppending {len(clip_infos)} clips to timeline...")
    appended = media_pool.AppendToTimeline(clip_infos)
    if not appended:
        print("ERROR: AppendToTimeline failed")
        sys.exit(1)
    print(f"  Appended {len(appended)} clips")

    # Read back timeline positions for SRT
    all_items = timeline.GetItemListInTrack("video", 1)
    # New items start after original end frame
    new_items = [item for item in all_items if item.GetStart() >= timeline_end_frame]

    subtitle_timings = []
    for item, clip in zip(new_items, ordered_clips):
        if clip.get("subtitle") and not clip.get("is_action"):
            subtitle_timings.append({
                "name": clip["name"],
                "text": clip["subtitle"],
                "start_seconds": item.GetStart() / fps,
                "end_seconds": item.GetEnd() / fps,
            })

    if subtitle_timings:
        srt_path = srt_output or os.path.join(
            os.path.dirname(manifest_path), "recut.srt"
        )
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(build_srt(subtitle_timings))
        print(f"\n  SRT: {srt_path} ({len(subtitle_timings)} subtitles)")
        print("  -> Drag recut.srt onto the subtitle track")

    resolve.OpenPage("edit")
    print(f"\nDone! {len(appended)} clips appended to '{project_name}'.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest")
    parser.add_argument("clips_dir")
    parser.add_argument("--project", required=True)
    parser.add_argument("--fps", type=float, default=23.976)
    parser.add_argument("--srt")
    args = parser.parse_args()
    resolve_append(args.manifest, args.clips_dir, args.project, args.fps, args.srt)


if __name__ == "__main__":
    main()
