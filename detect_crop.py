"""Detect letterboxing/pillarboxing in video files.

Samples frames at intervals and runs ffmpeg cropdetect to find
consistent crop values. Outputs a crop filter string for ffmpeg.

Usage:
    python detect_crop.py <video_path>
    python detect_crop.py <video_dir> --all
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter


def detect_crop(
    video_path: str,
    sample_points: int = 5,
    duration_fraction: float = 0.8,
    ffmpeg_path: str = "ffmpeg",
) -> str | None:
    """Detect letterbox crop values for a video file.

    Samples multiple points throughout the video to get a consistent reading,
    avoiding the very start/end where fades or title cards may skew results.

    Args:
        video_path: Path to video file
        sample_points: Number of points to sample
        duration_fraction: How far into the video to sample (0.8 = first 80%)
        ffmpeg_path: Path to ffmpeg binary

    Returns:
        Crop filter string like "crop=1920:960:0:60", or None if no crop needed
    """
    # Get video duration
    probe_cmd = [
        ffmpeg_path.replace("ffmpeg", "ffprobe"),
        "-v", "quiet",
        "-show_entries", "format=duration",
        "-show_entries", "stream=width,height",
        "-of", "default=noprint_wrappers=1",
        video_path,
    ]

    try:
        result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"Error probing video: {e}")
        return None

    duration = None
    orig_width = None
    orig_height = None
    for line in result.stdout.splitlines():
        key, _, val = line.partition("=")
        if val in ("", "N/A"):
            continue
        if key == "duration" and duration is None:
            duration = float(val)
        elif key == "width" and orig_width is None:
            orig_width = int(val)
        elif key == "height" and orig_height is None:
            orig_height = int(val)

    if not duration or not orig_width or not orig_height:
        print("Could not determine video properties.")
        return None

    # Sample points spread across the video, avoiding start/end
    start_offset = duration * 0.1
    end_offset = duration * duration_fraction
    interval = (end_offset - start_offset) / sample_points

    crops = Counter()

    for i in range(sample_points):
        seek_time = start_offset + (i * interval)

        cmd = [
            ffmpeg_path,
            "-ss", str(seek_time),
            "-i", video_path,
            "-vframes", "10",
            "-vf", "cropdetect=24:16:0",
            "-f", "null",
            "-",
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            # Parse cropdetect output from stderr
            for line in result.stderr.splitlines():
                match = re.search(r"crop=(\d+:\d+:\d+:\d+)", line)
                if match:
                    crops[match.group(1)] += 1
        except subprocess.CalledProcessError:
            continue

    if not crops:
        print("Could not detect crop values.")
        return None

    # Most common crop value
    best_crop, count = crops.most_common(1)[0]
    w, h, x, y = [int(v) for v in best_crop.split(":")]

    # Check if crop is actually needed (matches original dimensions)
    if w == orig_width and h == orig_height:
        print(f"No letterboxing detected ({orig_width}x{orig_height})")
        return None

    crop_str = f"crop={best_crop}"
    removed_h = orig_height - h
    removed_w = orig_width - w

    print(f"Original:  {orig_width}x{orig_height}")
    print(f"Cropped:   {w}x{h} (offset {x},{y})")
    if removed_h > 0:
        print(f"Letterbox: {removed_h}px total ({y}px top, {removed_h - y}px bottom)")
    if removed_w > 0:
        print(f"Pillarbox: {removed_w}px total ({x}px left, {removed_w - x}px right)")
    print(f"Filter:    -vf \"{crop_str}\"")
    print(f"Confidence: {count}/{sum(crops.values())} samples agree")

    return crop_str


def main():
    parser = argparse.ArgumentParser(
        description="Detect letterboxing/pillarboxing in video files"
    )
    parser.add_argument("path", help="Video file or directory")
    parser.add_argument(
        "--all", action="store_true", help="Scan all video files in directory"
    )
    parser.add_argument(
        "--samples", type=int, default=5, help="Number of sample points (default: 5)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    ffmpeg_path = "ffmpeg"
    try:
        from config_loader import load_config
        config = load_config()
        ffmpeg_path = config.get("ffmpeg_path", "ffmpeg")
    except ImportError:
        pass

    if os.path.isdir(args.path) and args.all:
        results = {}
        for f in sorted(os.listdir(args.path)):
            if f.endswith((".mkv", ".mp4", ".avi", ".mov")):
                filepath = os.path.join(args.path, f)
                print(f"\n=== {f} ===")
                crop = detect_crop(filepath, args.samples, ffmpeg_path=ffmpeg_path)
                if crop:
                    results[f] = crop

        if args.json:
            print(json.dumps(results, indent=2))
    else:
        crop = detect_crop(args.path, args.samples, ffmpeg_path=ffmpeg_path)
        if args.json:
            print(json.dumps({"crop": crop}))
        if not crop:
            sys.exit(1)


if __name__ == "__main__":
    main()
