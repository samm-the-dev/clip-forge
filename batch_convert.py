"""Batch convert MKV clips to MP4 with crop, stereo AAC, and re-encode.

Reads a manifest or scans a clips directory, applies letterbox cropping
and audio downmix, outputs MP4 files ready for Resolve import.

Usage:
    python batch_convert.py <manifest.json> [--crop auto] [--output-dir <dir>]
    python batch_convert.py <clips_dir> --crop "1920:960:0:60"
"""

import argparse
import json
import os
import subprocess

from detect_crop import detect_crop


def convert_clip(
    input_path: str,
    output_path: str,
    crop: str = None,
    crf: int = 18,
    audio_bitrate: str = "192k",
    ffmpeg_path: str = "ffmpeg",
) -> bool:
    """Convert a single clip to MP4 with optional crop and stereo downmix.

    Args:
        input_path: Source MKV/video file
        output_path: Output MP4 path
        crop: Crop filter string like "crop=1920:960:0:60", or None
        crf: H.264 CRF quality (lower = better, 18 is visually lossless)
        audio_bitrate: AAC audio bitrate
        ffmpeg_path: Path to ffmpeg binary

    Returns:
        True on success
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    vf_parts = []
    if crop:
        vf_parts.append(crop)

    cmd = [
        ffmpeg_path, "-y",
        "-i", input_path,
    ]

    if vf_parts:
        cmd.extend(["-vf", ",".join(vf_parts)])

    cmd.extend([
        "-c:v", "libx264", "-preset", "fast", "-crf", str(crf),
        "-c:a", "aac", "-b:a", audio_bitrate, "-ac", "2",
        output_path,
    ])

    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def batch_convert(
    manifest_path: str = None,
    clips_dir: str = None,
    output_dir: str = None,
    crop: str = None,
    auto_crop: bool = False,
    crf: int = 18,
    ffmpeg_path: str = "ffmpeg",
) -> list[str]:
    """Batch convert clips to MP4.

    Args:
        manifest_path: Path to cut_manifest.json (uses output paths for MKV sources)
        clips_dir: Alternative: directory of MKV files to convert
        output_dir: Override output directory
        crop: Explicit crop filter, or None
        auto_crop: Detect crop from first video file
        crf: H.264 CRF quality
        ffmpeg_path: Path to ffmpeg binary

    Returns:
        List of output MP4 paths
    """
    # Build file list
    if manifest_path:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        files = []
        for entry in manifest:
            mkv_path = entry.get("output", "")
            if os.path.exists(mkv_path):
                files.append((mkv_path, entry["name"]))
            else:
                # Try in output_dir or clips_dir
                alt = os.path.join(
                    output_dir or os.path.dirname(mkv_path),
                    f"{entry['name']}.mkv",
                )
                if os.path.exists(alt):
                    files.append((alt, entry["name"]))
                else:
                    print(f"  SKIP {entry['name']}: MKV not found")
    elif clips_dir:
        files = [
            (os.path.join(clips_dir, f), os.path.splitext(f)[0])
            for f in sorted(os.listdir(clips_dir))
            if f.endswith(".mkv")
        ]
    else:
        print("ERROR: Provide either a manifest or clips directory")
        return []

    if not files:
        print("No MKV files found to convert.")
        return []

    # Auto-detect crop from first file
    if auto_crop and crop is None:
        print(f"Auto-detecting crop from {os.path.basename(files[0][0])}...")
        crop = detect_crop(files[0][0], ffmpeg_path=ffmpeg_path)
        if crop:
            print(f"  Using: -vf \"{crop}\"")
        else:
            print("  No letterboxing detected")

    # Convert
    out_dir = output_dir or os.path.dirname(files[0][0])
    outputs = []

    for i, (mkv_path, name) in enumerate(files, 1):
        mp4_path = os.path.join(out_dir, f"{name}.mp4")
        success = convert_clip(
            mkv_path, mp4_path,
            crop=crop, crf=crf, ffmpeg_path=ffmpeg_path,
        )
        if success:
            size_mb = os.path.getsize(mp4_path) / (1024 * 1024)
            print(f"  [{i}/{len(files)}] {name}.mp4 ({size_mb:.1f}MB)")
            outputs.append(mp4_path)
        else:
            print(f"  FAIL [{i}/{len(files)}] {name}")

    return outputs


def main():
    parser = argparse.ArgumentParser(
        description="Batch convert MKV clips to cropped stereo MP4"
    )
    parser.add_argument("input", help="Path to cut_manifest.json or clips directory")
    parser.add_argument("--output-dir", "-o", help="Output directory for MP4 files")
    parser.add_argument(
        "--crop", default=None,
        help='Crop filter (e.g. "crop=1920:960:0:60") or "auto" to detect'
    )
    parser.add_argument("--crf", type=int, default=18, help="H.264 CRF quality (default: 18)")
    args = parser.parse_args()

    ffmpeg_path = "ffmpeg"
    try:
        from config_loader import load_config
        config = load_config()
        ffmpeg_path = config.get("ffmpeg_path", "ffmpeg")
    except ImportError:
        pass

    auto_crop = args.crop == "auto"
    crop = None if auto_crop else args.crop

    is_manifest = args.input.endswith(".json")

    print(f"Converting clips to MP4...")
    outputs = batch_convert(
        manifest_path=args.input if is_manifest else None,
        clips_dir=args.input if not is_manifest else None,
        output_dir=args.output_dir,
        crop=crop,
        auto_crop=auto_crop,
        crf=args.crf,
        ffmpeg_path=ffmpeg_path,
    )
    print(f"\nDone: {len(outputs)} clips converted")


if __name__ == "__main__":
    main()
