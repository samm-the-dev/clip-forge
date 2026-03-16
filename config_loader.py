"""Configuration loader for Clip Forge."""

import json
import os
from pathlib import Path

DEFAULT_CONFIG = {
    "media_paths": {},
    "output_dir": "",
    "ffmpeg_path": "ffmpeg",
    "padding_seconds": 3,
    "default_fps": 15,
    "default_width": 480,
}


def load_config(config_path: str = None) -> dict:
    """Load config from JSON file, falling back to defaults."""
    if config_path is None:
        config_path = os.path.join(os.path.dirname(__file__), "config.json")

    config = DEFAULT_CONFIG.copy()

    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            user_config = json.load(f)
            config.update(user_config)
    else:
        print(f"Warning: No config.json found at {config_path}")
        print("Copy config.example.json to config.json and set your paths.")

    # Ensure output directories exist
    if config["output_dir"]:
        clips_dir = os.path.join(config["output_dir"], "clips")
        os.makedirs(clips_dir, exist_ok=True)

    return config
