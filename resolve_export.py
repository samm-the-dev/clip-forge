"""Export individual animated WebP clips from DaVinci Resolve via the scripting API.

Reads the current timeline, sets up per-clip render jobs with WebP format
and subtitle burn-in, then renders all jobs.

Requires:
    - DaVinci Resolve Studio running with a timeline open
    - Python 3.8 (Resolve 20.x DLL is compiled against 3.8)
    - Run via: uv run --python 3.8 resolve_export.py --output <dir>

Usage:
    uv run --python 3.8 resolve_export.py <manifest.json> --output <dir>
    uv run --python 3.8 resolve_export.py <manifest.json> --output <dir> --width 640
    uv run --python 3.8 resolve_export.py --output <dir> --auto-name
    uv run --python 3.8 resolve_export.py --output <dir> --name monsters_together
"""

import argparse
import json
import os
import re
import sys
import time


def get_resolve():
    """Connect to DaVinci Resolve via the scripting API."""
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


def slugify(text):
    """Convert text to a filename-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[''']", "", text)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")[:60]


def get_clip_names_from_manifest(manifest_path):
    """Load clip names from a manifest file."""
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    return [entry["name"] for entry in manifest]


def get_clip_names_from_subtitles(timeline, clips):
    """Auto-generate clip names from the subtitle track."""
    sub_items = timeline.GetItemListInTrack("subtitle", 1) or []

    # Build a map of subtitle text by frame range
    sub_map = []
    for item in sub_items:
        start = item.GetStart()
        end = item.GetEnd()
        name = item.GetName() or ""
        sub_map.append((start, end, name))

    names = []
    for i, clip in enumerate(clips):
        clip_start = clip.GetStart()
        clip_end = clip.GetEnd()

        # Find subtitle overlapping this clip
        subtitle_text = None
        for sub_start, sub_end, sub_name in sub_map:
            if sub_start < clip_end and sub_end > clip_start:
                subtitle_text = sub_name
                break

        if subtitle_text:
            names.append(slugify(subtitle_text))
        else:
            names.append("clip_%02d" % (i + 1))

    return names


def resolve_export(
    output_dir,
    manifest_path=None,
    auto_name=False,
    width=640,
    height=None,
    clip_filter=None,
):
    """Export timeline clips as individual animated WebP files.

    Args:
        output_dir: Directory for WebP output files
        manifest_path: Path to cut_manifest.json (for clip names)
        auto_name: Auto-generate names from subtitle track
        width: Output width (default 640)
        height: Output height (default: auto from timeline aspect ratio)
        clip_filter: Optional set of clip names to export (exports all if None)
    """
    resolve = get_resolve()
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        print("ERROR: No project open")
        sys.exit(1)

    timeline = project.GetCurrentTimeline()
    if not timeline:
        print("ERROR: No timeline open")
        sys.exit(1)

    fps = float(timeline.GetSetting("timelineFrameRate"))
    tl_width = int(timeline.GetSetting("timelineResolutionWidth"))
    tl_height = int(timeline.GetSetting("timelineResolutionHeight"))

    # Auto-calculate height from aspect ratio
    if height is None:
        height = round(width * tl_height / tl_width)
        # Round to even number (required by some codecs)
        height = height + (height % 2)

    print("Timeline: %s (%dx%d @ %sfps)" % (timeline.GetName(), tl_width, tl_height, fps))
    print("Export:   %dx%d WebP" % (width, height))

    clips = timeline.GetItemListInTrack("video", 1)
    if not clips:
        print("ERROR: No clips on video track 1")
        sys.exit(1)

    # Determine clip names
    if manifest_path:
        names = get_clip_names_from_manifest(manifest_path)
        if len(names) != len(clips):
            print("WARNING: manifest has %d names but timeline has %d clips" % (len(names), len(clips)))
            names = names[: len(clips)] if len(names) > len(clips) else names + [
                "clip_%02d" % (i + 1) for i in range(len(names), len(clips))
            ]
    elif auto_name:
        names = get_clip_names_from_subtitles(timeline, clips)
    else:
        names = ["clip_%02d" % (i + 1) for i in range(len(clips))]

    # Set format
    project.SetCurrentRenderFormatAndCodec("webp", "Animated_WEBP")

    # Clear existing render jobs
    for job in project.GetRenderJobList():
        project.DeleteRenderJob(job["JobId"])

    # Group clips by name — merges split clips (same source file) into one job
    from collections import OrderedDict
    name_groups = OrderedDict()
    for clip, name in zip(clips, names):
        if name not in name_groups:
            name_groups[name] = []
        name_groups[name].append(clip)

    # Queue render jobs
    os.makedirs(output_dir, exist_ok=True)
    queued = []

    for name, group_clips in name_groups.items():
        if clip_filter and name not in clip_filter:
            continue

        start_frame = min(c.GetStart() for c in group_clips)
        end_frame = max(c.GetEnd() for c in group_clips)
        frame_count = end_frame - start_frame

        settings = {
            "FormatWidth": width,
            "FormatHeight": height,
            "MarkIn": start_frame,
            "MarkOut": end_frame - 1,
            "CustomName": name,
            "TargetDir": output_dir,
            "ExportAlpha": False,
            "IsExportAudio": False,
            "IsExportVideo": True,
        }

        project.SetRenderSettings(settings)
        job_id = project.AddRenderJob()
        if job_id:
            queued.append((name, job_id, frame_count))
            print("  queued: %s (%d frames)" % (name, frame_count))
        else:
            print("  FAIL:  %s (could not add render job)" % name)

    if not queued:
        print("\nNo clips to render.")
        return []

    # Render
    print("\nRendering %d clips..." % len(queued))
    project.StartRendering()

    while project.IsRenderingInProgress():
        time.sleep(1)

    # Report results
    print("\nResults:")
    results = []
    for name, job_id, frame_count in queued:
        status = project.GetRenderJobStatus(job_id)
        job_status = status.get("JobStatus", "Unknown")
        webp_path = os.path.join(output_dir, "%s.webp" % name)

        if os.path.exists(webp_path):
            size_kb = os.path.getsize(webp_path) / 1024
            print("  %s: %s (%.0fKB)" % (name, job_status, size_kb))
            results.append({"name": name, "path": webp_path, "size_kb": round(size_kb), "status": job_status})
        else:
            print("  %s: %s (file not found)" % (name, job_status))
            results.append({"name": name, "path": webp_path, "size_kb": 0, "status": job_status})

    total_kb = sum(r["size_kb"] for r in results)
    print("\nDone: %d clips, %.1fMB total" % (len(results), total_kb / 1024))
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Export individual animated WebP clips from DaVinci Resolve"
    )
    parser.add_argument("manifest", nargs="?", help="Path to cut_manifest.json (for clip names)")
    parser.add_argument("--output", "-o", required=True, help="Output directory for WebP files")
    parser.add_argument("--width", type=int, default=640, help="Output width (default: 640)")
    parser.add_argument("--height", type=int, default=None, help="Output height (default: auto from aspect ratio)")
    parser.add_argument("--auto-name", action="store_true", help="Auto-name clips from subtitle track")
    parser.add_argument("--name", nargs="*", help="Export only specific clip name(s)")
    args = parser.parse_args()

    if not args.manifest and not args.auto_name:
        print("Provide a manifest for clip names, or use --auto-name to detect from subtitles")
        sys.exit(1)

    resolve_export(
        output_dir=args.output,
        manifest_path=args.manifest,
        auto_name=args.auto_name,
        width=args.width,
        height=args.height,
        clip_filter=set(args.name) if args.name else None,
    )


if __name__ == "__main__":
    main()
