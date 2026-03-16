"""Subtitle extraction and search for finding moments in video files."""

import os
import re
import subprocess
import tempfile
from difflib import SequenceMatcher


def get_subtitle_tracks(video_path: str, ffmpeg_path: str = "ffmpeg") -> list[dict]:
    """List available subtitle tracks in a video file using ffprobe.

    Returns:
        List of dicts with keys: index, codec, language, title
    """
    ffprobe = ffmpeg_path.replace("ffmpeg", "ffprobe")
    cmd = [
        ffprobe,
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-select_streams", "s",
        video_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        import json
        data = json.loads(result.stdout)
        tracks = []
        for stream in data.get("streams", []):
            tracks.append({
                "index": stream.get("index"),
                "codec": stream.get("codec_name", "unknown"),
                "language": stream.get("tags", {}).get("language", "und"),
                "title": stream.get("tags", {}).get("title", ""),
            })
        return tracks
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"Error probing subtitles: {e}")
        return []


def extract_subtitles(
    video_path: str,
    output_path: str = None,
    track_index: int = 0,
    ffmpeg_path: str = "ffmpeg",
) -> str:
    """Extract subtitles from a video file to .srt format.

    Args:
        video_path: Path to video file
        output_path: Where to save the .srt (default: temp file)
        track_index: Which subtitle stream to extract (0-based among subtitle streams)
        ffmpeg_path: Path to ffmpeg binary

    Returns:
        Path to the extracted .srt file
    """
    if output_path is None:
        fd, output_path = tempfile.mkstemp(suffix=".srt")
        os.close(fd)

    cmd = [
        ffmpeg_path,
        "-y",
        "-i", video_path,
        "-map", f"0:s:{track_index}",
        "-c:s", "srt",
        output_path,
    ]

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return output_path
    except subprocess.CalledProcessError as e:
        print(f"Error extracting subtitles: {e.stderr}")
        return None


def parse_srt(srt_path: str) -> list[dict]:
    """Parse an .srt file into a list of subtitle entries.

    Returns:
        List of dicts with keys: index, start, end, start_seconds, end_seconds, text
    """
    try:
        import pysrt
        subs = pysrt.open(srt_path)
        entries = []
        for sub in subs:
            entries.append({
                "index": sub.index,
                "start": str(sub.start).replace(",", "."),
                "end": str(sub.end).replace(",", "."),
                "start_seconds": (
                    sub.start.hours * 3600
                    + sub.start.minutes * 60
                    + sub.start.seconds
                    + sub.start.milliseconds / 1000
                ),
                "end_seconds": (
                    sub.end.hours * 3600
                    + sub.end.minutes * 60
                    + sub.end.seconds
                    + sub.end.milliseconds / 1000
                ),
                "text": sub.text.replace("\n", " "),
            })
        return entries
    except ImportError:
        # Fallback: manual SRT parsing
        return _parse_srt_manual(srt_path)


def _parse_srt_manual(srt_path: str) -> list[dict]:
    """Manual SRT parser as fallback if pysrt is not installed."""
    with open(srt_path, "r", encoding="utf-8-sig") as f:
        content = f.read()

    entries = []
    blocks = re.split(r"\n\n+", content.strip())

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue

        try:
            index = int(lines[0])
        except ValueError:
            continue

        time_match = re.match(
            r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})",
            lines[1],
        )
        if not time_match:
            continue

        start_str = time_match.group(1).replace(",", ".")
        end_str = time_match.group(2).replace(",", ".")
        text = " ".join(lines[2:]).strip()
        # Strip HTML-style tags from subtitle text
        text = re.sub(r"<[^>]+>", "", text)

        entries.append({
            "index": index,
            "start": start_str,
            "end": end_str,
            "start_seconds": _timestamp_to_seconds(start_str),
            "end_seconds": _timestamp_to_seconds(end_str),
            "text": text,
        })

    return entries


def _timestamp_to_seconds(ts: str) -> float:
    """Convert HH:MM:SS.mmm to seconds."""
    parts = ts.split(":")
    hours = int(parts[0])
    minutes = int(parts[1])
    sec_parts = parts[2].split(".")
    seconds = int(sec_parts[0])
    millis = int(sec_parts[1]) if len(sec_parts) > 1 else 0
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def search_subtitles(
    entries: list[dict], query: str, context_lines: int = 3, limit: int = 5
) -> list[dict]:
    """Search subtitle entries for lines matching a query.

    Uses fuzzy matching to handle paraphrased descriptions.

    Args:
        entries: Parsed subtitle entries
        query: What the user is looking for (dialogue, description, etc.)
        context_lines: Number of surrounding subtitle lines to include
        limit: Max results

    Returns:
        List of match dicts with keys: match, score, context_before, context_after,
        range_start, range_end (timestamps for the context window)
    """
    query_lower = query.lower().strip()
    query_words = set(query_lower.split())

    scored = []
    for i, entry in enumerate(entries):
        text_lower = entry["text"].lower()

        # Exact substring match
        if query_lower in text_lower:
            score = 1.0
        else:
            # Fuzzy match
            score = SequenceMatcher(None, query_lower, text_lower).ratio()

            # Boost for word overlap
            text_words = set(text_lower.split())
            overlap = query_words & text_words
            if overlap:
                score += len(overlap) / len(query_words) * 0.3

        if score > 0.3:
            # Gather context
            start_idx = max(0, i - context_lines)
            end_idx = min(len(entries) - 1, i + context_lines)

            context_before = entries[start_idx:i]
            context_after = entries[i + 1 : end_idx + 1]

            scored.append({
                "match": entry,
                "score": score,
                "context_before": context_before,
                "context_after": context_after,
                "range_start": entries[start_idx]["start"],
                "range_start_seconds": entries[start_idx]["start_seconds"],
                "range_end": entries[end_idx]["end"],
                "range_end_seconds": entries[end_idx]["end_seconds"],
            })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]


def format_search_results(results: list[dict]) -> str:
    """Format search results for display."""
    if not results:
        return "No matching subtitle lines found."

    output = []
    for i, r in enumerate(results, 1):
        output.append(f"\n--- Match {i} (score: {r['score']:.2f}) ---")
        output.append(f"Timestamp: {r['match']['start']} -> {r['match']['end']}")
        output.append(f"Context window: {r['range_start']} -> {r['range_end']}")
        output.append("")

        for ctx in r["context_before"]:
            output.append(f"  [{ctx['start']}] {ctx['text']}")

        output.append(f"  [{r['match']['start']}] >>> {r['match']['text']} <<<")

        for ctx in r["context_after"]:
            output.append(f"  [{ctx['start']}] {ctx['text']}")

    return "\n".join(output)
