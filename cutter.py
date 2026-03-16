"""FFmpeg-based video cutting for extracting clip segments."""

import os
import re
import subprocess


def seconds_to_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS.mmm format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def cut_clip(
    video_path: str,
    start_seconds: float,
    end_seconds: float,
    output_path: str,
    padding_seconds: float = 3.0,
    ffmpeg_path: str = "ffmpeg",
) -> str:
    """Extract a clip from a video file with padding.

    Args:
        video_path: Source video file
        start_seconds: Start time in seconds
        end_seconds: End time in seconds
        output_path: Where to save the clip
        padding_seconds: Extra seconds before/after the target range
        ffmpeg_path: Path to ffmpeg binary

    Returns:
        Path to the output clip, or None on failure
    """
    # Apply padding
    padded_start = max(0, start_seconds - padding_seconds)
    padded_end = end_seconds + padding_seconds

    start_ts = seconds_to_timestamp(padded_start)
    duration = padded_end - padded_start
    duration_ts = seconds_to_timestamp(duration)

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    cmd = [
        ffmpeg_path,
        "-y",
        "-ss", start_ts,
        "-i", video_path,
        "-t", duration_ts,
        "-c", "copy",          # Stream copy for speed (no re-encode)
        "-avoid_negative_ts", "make_zero",
        output_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(f"Clip saved: {output_path}")
        print(f"Range: {start_ts} -> {seconds_to_timestamp(padded_end)} "
              f"(target: {seconds_to_timestamp(start_seconds)} -> "
              f"{seconds_to_timestamp(end_seconds)}, "
              f"padding: {padding_seconds}s)")
        return output_path
    except subprocess.CalledProcessError as e:
        print(f"Error cutting clip: {e.stderr}")
        return None


def generate_clip_filename(video_path: str, start_seconds: float) -> str:
    """Generate a descriptive filename for a clip.

    Example: "Severance_S02E04_at_23m15s.mkv"
    """
    base = os.path.splitext(os.path.basename(video_path))[0]
    # Clean up the name
    base = re.sub(r"[^\w\s-]", "", base).strip()
    base = re.sub(r"\s+", "_", base)

    minutes = int(start_seconds // 60)
    seconds = int(start_seconds % 60)

    ext = os.path.splitext(video_path)[1]
    return f"{base}_at_{minutes}m{seconds}s{ext}"


def extract_thumbnails(
    video_path: str,
    timestamps: list[float],
    output_dir: str,
    ffmpeg_path: str = "ffmpeg",
) -> list[str]:
    """Extract thumbnail frames at specific timestamps for visual confirmation.

    Args:
        video_path: Source video
        timestamps: List of timestamps in seconds
        output_dir: Where to save thumbnails
        ffmpeg_path: Path to ffmpeg

    Returns:
        List of thumbnail file paths
    """
    os.makedirs(output_dir, exist_ok=True)
    thumbnails = []

    for i, ts in enumerate(timestamps):
        output_path = os.path.join(output_dir, f"thumb_{i:03d}_{ts:.1f}s.jpg")
        cmd = [
            ffmpeg_path,
            "-y",
            "-ss", seconds_to_timestamp(ts),
            "-i", video_path,
            "-vframes", "1",
            "-q:v", "2",
            output_path,
        ]

        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            thumbnails.append(output_path)
        except subprocess.CalledProcessError:
            pass

    return thumbnails
