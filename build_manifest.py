"""Build a cut manifest from a clip list file.

Reads a simple text format describing clips, searches cached subtitles
for dialogue clips, and outputs a cut_manifest.json ready for batch processing.

Input format (one clip per line):
    ep01 12:30 "dialogue to search"           # dialogue clip
    ep01 12:30-12:45 "dialogue to search"     # dialogue with explicit range
    ep01 12:30 [action] short_name             # action clip (no subtitle search)
    ep01 12:30-12:45 [action] short_name       # action with explicit range

Episode format: ep01, ep1, 1 (all equivalent)
Timestamps: MM:SS or HH:MM:SS
"""

import argparse
import json
import os
import re
import sys

from config_loader import load_config
from subtitle_search import (
    extract_subtitles,
    get_subtitle_tracks,
    parse_srt,
    search_subtitles,
)


def parse_clip_line(line: str) -> dict | None:
    """Parse a single clip definition line.

    Returns dict with keys: ep, time_start, time_end, query, is_action, name
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    # Match episode number
    ep_match = re.match(r"ep?(\d+)\s+", line, re.IGNORECASE)
    if not ep_match:
        return None

    ep = int(ep_match.group(1))
    rest = line[ep_match.end():]

    # Match timestamp or timestamp range
    ts_pattern = r"(\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)"
    range_match = re.match(rf"{ts_pattern}(?:\s*-\s*{ts_pattern})?\s+", rest)
    if not range_match:
        return None

    time_start = range_match.group(1)
    time_end = range_match.group(2)  # None if no range
    rest = rest[range_match.end():]

    # Check for action tag
    is_action = False
    action_match = re.match(r"\[action\]\s*", rest, re.IGNORECASE)
    if action_match:
        is_action = True
        rest = rest[action_match.end():]

    # Remaining is either a quoted dialogue query or a name
    query = None
    name = None

    quoted = re.match(r'"([^"]+)"(?:\s+(\S+))?', rest)
    if quoted:
        query = quoted.group(1)
        name = quoted.group(2)
    else:
        name = rest.strip() or None

    return {
        "ep": ep,
        "time_start": time_start,
        "time_end": time_end,
        "query": query,
        "is_action": is_action,
        "name": name,
    }


def timestamp_to_seconds(ts: str) -> float:
    """Convert MM:SS or HH:MM:SS to seconds."""
    parts = ts.replace(",", ".").split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(ts)


def slugify(text: str) -> str:
    """Convert text to a filename-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[''']", "", text)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def find_episode_file(ep_num: int, media_dir: str) -> str | None:
    """Find the video file for a given episode number."""
    for root, _, files in os.walk(media_dir):
        for f in sorted(files):
            if re.search(rf"[ES]\d*0?{ep_num}\b", f, re.IGNORECASE) and f.endswith(
                (".mkv", ".mp4", ".avi")
            ):
                return os.path.join(root, f)
    return None


def get_cached_subs(ep_num: int, cache_dir: str) -> list[dict] | None:
    """Load cached subtitle entries for an episode."""
    json_path = os.path.join(cache_dir, f"ep{ep_num:02d}.json")
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def cache_subtitles(
    ep_num: int, video_path: str, cache_dir: str, ffmpeg_path: str = "ffmpeg"
) -> list[dict] | None:
    """Extract, cache, and return subtitle entries for an episode."""
    os.makedirs(cache_dir, exist_ok=True)

    tracks = get_subtitle_tracks(video_path, ffmpeg_path)
    if not tracks:
        print(f"  No subtitle tracks found in {video_path}")
        return None

    # Find English non-SDH track
    eng_tracks = [t for t in tracks if t["language"] == "eng"]
    if eng_tracks:
        non_sdh = [t for t in eng_tracks if "sdh" not in t.get("title", "").lower()]
        chosen = non_sdh[0] if non_sdh else eng_tracks[0]
        track_idx = next(
            i for i, t in enumerate(tracks) if t["index"] == chosen["index"]
        )
    else:
        track_idx = 0

    srt_out = os.path.join(cache_dir, f"ep{ep_num:02d}.srt")
    srt_path = extract_subtitles(
        video_path, output_path=srt_out, track_index=track_idx, ffmpeg_path=ffmpeg_path
    )
    if not srt_path:
        return None

    entries = parse_srt(srt_path)

    # Save as JSON for fast loading
    json_out = os.path.join(cache_dir, f"ep{ep_num:02d}.json")
    with open(json_out, "w", encoding="utf-8") as f:
        json.dump(
            [
                {
                    "start": e["start"],
                    "end": e["end"],
                    "start_seconds": e["start_seconds"],
                    "end_seconds": e["end_seconds"],
                    "text": e["text"],
                }
                for e in entries
            ],
            f,
            indent=2,
        )

    print(f"  Cached {len(entries)} subtitle entries for ep{ep_num:02d}")
    return entries


def build_manifest(
    clip_list_path: str,
    media_dir: str,
    project_dir: str,
    padding: float = 3.0,
    ffmpeg_path: str = "ffmpeg",
) -> list[dict]:
    """Build a cut manifest from a clip list file.

    Args:
        clip_list_path: Path to the clip list text file
        media_dir: Directory containing episode video files
        project_dir: Project output directory (for cache, clips, etc.)
        padding: Seconds of padding around each clip
        ffmpeg_path: Path to ffmpeg binary

    Returns:
        List of manifest entries
    """
    cache_dir = os.path.join(project_dir, "subs_cache")

    with open(clip_list_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    clips = []
    for i, line in enumerate(lines, 1):
        parsed = parse_clip_line(line)
        if parsed is None:
            continue
        parsed["_line"] = i
        clips.append(parsed)

    if not clips:
        print("No valid clips found in input file.")
        return []

    print(f"Parsed {len(clips)} clips from {clip_list_path}\n")

    # Determine which episodes need subtitles
    dialogue_eps = {c["ep"] for c in clips if not c["is_action"] and c["query"]}

    # Ensure subtitle caches exist
    for ep in sorted(dialogue_eps):
        subs = get_cached_subs(ep, cache_dir)
        if subs is None:
            print(f"Caching subtitles for ep{ep:02d}...")
            video = find_episode_file(ep, media_dir)
            if video:
                cache_subtitles(ep, video, cache_dir, ffmpeg_path)
            else:
                print(f"  WARNING: Could not find video file for ep{ep:02d}")

    # Build manifest entries
    manifest = []
    for clip in clips:
        ep = clip["ep"]
        entry = {
            "ep": ep,
            "is_action": clip["is_action"],
            "padding": padding,
        }

        ref_seconds = timestamp_to_seconds(clip["time_start"])

        if clip["query"] and not clip["is_action"]:
            # Search subtitles for the dialogue
            subs = get_cached_subs(ep, cache_dir)
            if subs is None:
                print(f"  WARNING: No subs for ep{ep:02d}, skipping: {clip['query']}")
                continue

            matches = search_subtitles(subs, clip["query"])
            if not matches:
                print(f"  WARNING: No match for '{clip['query']}' in ep{ep:02d}")
                continue

            # If multiple matches, prefer the one closest to the given timestamp
            best = matches[0]
            if len(matches) > 1:
                best = min(
                    matches,
                    key=lambda m: abs(m["match"]["start_seconds"] - ref_seconds),
                )

            entry["subtitle"] = best["match"]["text"]
            entry["start"] = best["match"]["start_seconds"] - 1.5
            entry["end"] = best["match"]["end_seconds"] + 1.5
            entry["search_score"] = best["score"]
            entry["name"] = clip["name"] or f"ep{ep:02d}_{slugify(clip['query'])}"
        else:
            # Action clip or no query — use timestamps directly
            entry["subtitle"] = clip["name"] or ""
            entry["start"] = ref_seconds
            if clip["time_end"]:
                entry["end"] = timestamp_to_seconds(clip["time_end"])
            else:
                entry["end"] = ref_seconds + 15  # default 15s for action clips
            entry["name"] = clip["name"] or f"ep{ep:02d}_action_{int(ref_seconds)}"

        # Find the source video path
        video = find_episode_file(ep, media_dir)
        if video:
            entry["source"] = video
        else:
            print(f"  WARNING: No video file for ep{ep:02d}")

        # Output path
        entry["output"] = os.path.join(project_dir, "clips", f"{entry['name']}.mkv")

        manifest.append(entry)
        tag = "ACTION" if entry["is_action"] else "DIALOGUE"
        print(f"  [{tag}] {entry['name']}: {entry['start']:.1f}s - {entry['end']:.1f}s")

    return manifest


def main():
    parser = argparse.ArgumentParser(
        description="Build a cut manifest from a clip list"
    )
    parser.add_argument("clip_list", help="Path to clip list text file")
    parser.add_argument("media_dir", help="Directory containing episode video files")
    parser.add_argument("project_dir", help="Project output directory")
    parser.add_argument(
        "--padding", type=float, default=3.0, help="Padding seconds (default: 3)"
    )
    parser.add_argument("--output", "-o", help="Output manifest path (default: project_dir/cut_manifest.json)")
    args = parser.parse_args()

    config = load_config()

    manifest = build_manifest(
        args.clip_list,
        args.media_dir,
        args.project_dir,
        padding=args.padding,
        ffmpeg_path=config["ffmpeg_path"],
    )

    if not manifest:
        print("\nNo manifest entries generated.")
        sys.exit(1)

    output_path = args.output or os.path.join(args.project_dir, "cut_manifest.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nManifest written: {output_path} ({len(manifest)} clips)")


if __name__ == "__main__":
    main()
