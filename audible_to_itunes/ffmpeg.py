"""FFmpeg and FFprobe utility functions."""

import json
import subprocess

from .config import DEBUG
from .processing_state import processing_state


def run_ffmpeg(args, log=print):
    """
    Run ffmpeg command with ability to be interrupted.
    Returns (success, stderr) tuple.
    """
    if processing_state.stop_requested:
        return False, "Stop requested"

    try:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        processing_state.set_process(proc)

        stdout, stderr = proc.communicate()
        processing_state.set_process(None)

        # Check if we were interrupted
        if processing_state.stop_requested:
            return False, "Stop requested"

        if proc.returncode != 0:
            if DEBUG:
                log(
                    f"    [FFmpeg Error] {stderr[-500:] if stderr else 'Unknown error'}"
                )
            return False, stderr

        return True, stderr
    except Exception as e:
        processing_state.set_process(None)
        return False, str(e)


def get_chapters_from_file(filepath):
    """
    Use FFprobe to extract chapter information directly from the .m4b file.
    Returns a list of chapter dicts with StartOffset and LengthInSeconds.
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_chapters",
                filepath,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if result.returncode != 0:
            if DEBUG:
                print(f"    [FFprobe Error] {result.stderr}")
            return []

        data = json.loads(result.stdout)
        chapters = []
        for ch in data.get("chapters", []):
            start_time = float(ch.get("start_time", 0))
            end_time = float(ch.get("end_time", start_time))
            chapters.append(
                {
                    "Name": ch.get("tags", {}).get(
                        "title", f"Chapter {len(chapters)+1}"
                    ),
                    "StartOffset": start_time,
                    "LengthInSeconds": end_time - start_time,
                }
            )
        return chapters
    except Exception as e:
        if DEBUG:
            print(f"    [FFprobe Exception] {e}")
        return []


def get_duration_from_file(filepath):
    """
    Use FFprobe to get the actual duration of the audio file in seconds.
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                filepath,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return float(data.get("format", {}).get("duration", 0))
    except Exception as e:
        if DEBUG:
            print(f"    [FFprobe Duration Error] {e}")
    return 0
