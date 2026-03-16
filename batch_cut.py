"""Batch cut clips from source videos using a manifest.

Reads cut_manifest.json and extracts MKV clips with FFmpeg stream copy.

Usage:
    python batch_cut.py <manifest.json> [--output-dir <dir>]
"""

import argparse
import json
import os
import subprocess

from cutter import seconds_to_timestamp


def batch_cut(
    manifest_path: str,
    output_dir: str = None,
    padding: float = None,
    ffmpeg_path: str = "ffmpeg",
) -> list[str]:
    """Cut all clips defined in a manifest.

    Args:
        manifest_path: Path to cut_manifest.json
        output_dir: Override output directory (default: uses manifest paths)
        padding: Override padding seconds (default: uses manifest values)
        ffmpeg_path: Path to ffmpeg binary

    Returns:
        List of output clip paths
    """
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    outputs = []
    for i, entry in enumerate(manifest, 1):
        source = entry.get("source")
        if not source or not os.path.exists(source):
            print(f"  SKIP [{i}/{len(manifest)}] {entry['name']}: source not found")
            continue

        pad = padding if padding is not None else entry.get("padding", 3)
        start = max(0, entry["start"] - pad)
        end = entry["end"] + pad

        if output_dir:
            out_path = os.path.join(output_dir, f"{entry['name']}.mkv")
        else:
            out_path = entry.get("output", os.path.join("clips", f"{entry['name']}.mkv"))

        os.makedirs(os.path.dirname(out_path), exist_ok=True)

        start_ts = seconds_to_timestamp(start)
        duration = end - start
        duration_ts = seconds_to_timestamp(duration)

        cmd = [
            ffmpeg_path, "-y",
            "-ss", start_ts,
            "-i", source,
            "-t", duration_ts,
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            out_path,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"  [{i}/{len(manifest)}] {entry['name']} -> {out_path}")
            outputs.append(out_path)
        else:
            print(f"  FAIL [{i}/{len(manifest)}] {entry['name']}: {result.stderr[-200:]}")

    return outputs


def main():
    parser = argparse.ArgumentParser(description="Batch cut clips from a manifest")
    parser.add_argument("manifest", help="Path to cut_manifest.json")
    parser.add_argument("--output-dir", "-o", help="Override output directory")
    parser.add_argument("--padding", type=float, help="Override padding seconds")
    args = parser.parse_args()

    ffmpeg_path = "ffmpeg"
    try:
        from config_loader import load_config
        config = load_config()
        ffmpeg_path = config.get("ffmpeg_path", "ffmpeg")
    except ImportError:
        pass

    print(f"Cutting clips from {args.manifest}...")
    outputs = batch_cut(
        args.manifest,
        output_dir=args.output_dir,
        padding=args.padding,
        ffmpeg_path=ffmpeg_path,
    )
    print(f"\nDone: {len(outputs)} clips cut")


if __name__ == "__main__":
    main()
