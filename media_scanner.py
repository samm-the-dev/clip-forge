"""Media library scanner and fuzzy file finder."""

import os
import re
from pathlib import Path
from difflib import SequenceMatcher


# Common video extensions
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".m4v", ".mov", ".wmv", ".ts"}


def scan_media_paths(media_paths: dict) -> list[dict]:
    """Scan configured media directories and return a list of media files with metadata.

    Args:
        media_paths: Dict like {"movies": "D:/Movies", "shows": "D:/TV Shows"}

    Returns:
        List of dicts with keys: path, filename, category, parsed_title, season, episode
    """
    results = []

    for category, base_path in media_paths.items():
        if not os.path.exists(base_path):
            print(f"Warning: Media path does not exist: {base_path}")
            continue

        for root, dirs, files in os.walk(base_path):
            for filename in files:
                ext = os.path.splitext(filename)[1].lower()
                if ext not in VIDEO_EXTENSIONS:
                    continue

                full_path = os.path.join(root, filename)
                parsed = parse_media_filename(filename, root, base_path)
                parsed["path"] = full_path
                parsed["filename"] = filename
                parsed["category"] = category
                results.append(parsed)

    return results


def parse_media_filename(filename: str, directory: str, base_path: str) -> dict:
    """Extract title, season, episode from filename and directory structure.

    Handles common patterns like:
        - Show Name/Season 01/S01E04 - Episode Title.mkv
        - Show.Name.S01E04.Episode.Title.mkv
        - Movie Name (2024).mkv
        - Movie.Name.2024.mkv
    """
    result = {"parsed_title": "", "season": None, "episode": None, "year": None}

    # Try S##E## pattern
    se_match = re.search(r"[Ss](\d{1,2})[Ee](\d{1,2})", filename)
    if se_match:
        result["season"] = int(se_match.group(1))
        result["episode"] = int(se_match.group(2))

    # Try to get show/movie title from directory structure
    rel_path = os.path.relpath(directory, base_path)
    parts = Path(rel_path).parts

    if parts and parts[0] != ".":
        # First directory under the media root is usually the title
        result["parsed_title"] = parts[0]
    else:
        # Fall back to filename - strip extension, year, S##E##, quality tags
        name = os.path.splitext(filename)[0]
        # Remove S##E## and everything after
        name = re.split(r"[Ss]\d{1,2}[Ee]\d{1,2}", name)[0]
        # Remove year in parens
        name = re.sub(r"\(\d{4}\)", "", name)
        # Replace dots and underscores with spaces
        name = re.sub(r"[._]", " ", name)
        result["parsed_title"] = name.strip(" -")

    # Try to extract year
    year_match = re.search(r"((?:19|20)\d{2})", filename)
    if year_match:
        result["year"] = int(year_match.group(1))

    return result


def find_media(query: str, media_paths: dict, limit: int = 10) -> list[dict]:
    """Find media files matching a natural language query.

    Handles queries like:
        - "severance s02e04"
        - "severance season 2 episode 4"
        - "the bear"
        - "inception"

    Args:
        query: Natural language search string
        media_paths: Config media paths dict
        limit: Max results to return

    Returns:
        List of matching media file dicts, sorted by relevance
    """
    all_media = scan_media_paths(media_paths)
    query_lower = query.lower().strip()

    # Parse season/episode from query if present
    query_season = None
    query_episode = None

    se_match = re.search(r"[Ss](\d{1,2})[Ee](\d{1,2})", query)
    if se_match:
        query_season = int(se_match.group(1))
        query_episode = int(se_match.group(2))
        # Remove S##E## from query for title matching
        title_query = re.sub(r"[Ss]\d{1,2}[Ee]\d{1,2}", "", query_lower).strip()
    else:
        # Try "season X episode Y" pattern
        se_match2 = re.search(r"season\s*(\d+)\s*episode\s*(\d+)", query_lower)
        if se_match2:
            query_season = int(se_match2.group(1))
            query_episode = int(se_match2.group(2))
            title_query = re.sub(
                r"season\s*\d+\s*episode\s*\d+", "", query_lower
            ).strip()
        else:
            title_query = query_lower

    scored = []
    for media in all_media:
        title = media["parsed_title"].lower()
        filename = media["filename"].lower()

        # Score title similarity
        title_score = SequenceMatcher(None, title_query, title).ratio()

        # Boost if query words appear in title
        query_words = title_query.split()
        word_hits = sum(1 for w in query_words if w in title or w in filename)
        word_score = word_hits / max(len(query_words), 1)

        score = (title_score * 0.6) + (word_score * 0.4)

        # Season/episode filtering — boost exact matches, penalize mismatches
        if query_season is not None:
            if media["season"] == query_season and media["episode"] == query_episode:
                score += 0.5
            elif media["season"] is not None:
                score -= 0.3

        scored.append((score, media))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored[:limit]]


def format_media_list(media_list: list[dict]) -> str:
    """Format media list for display."""
    lines = []
    for i, m in enumerate(media_list, 1):
        parts = [f"{i}. {m['parsed_title']}"]
        if m["season"] is not None:
            parts.append(f"S{m['season']:02d}E{m['episode']:02d}")
        if m["year"]:
            parts.append(f"({m['year']})")
        parts.append(f"\n   {m['path']}")
        lines.append(" ".join(parts))
    return "\n".join(lines)
