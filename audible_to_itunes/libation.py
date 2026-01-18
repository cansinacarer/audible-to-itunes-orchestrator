"""Libation CLI interaction functions."""

import os
import re
import subprocess

from .config import DEBUG, LIBATION_EXE


def run_cli(args, capture=False):
    """
    Runs Libation CLI and returns output text.
    During development (DEBUG=True), shows all output/errors.
    """
    if DEBUG and not capture:
        # Show output in real-time for debugging
        print(f"  [CMD] {LIBATION_EXE} {' '.join(args)}")
        result = subprocess.run([LIBATION_EXE] + args, text=True, encoding="utf-8")
        return ""
    else:
        result = subprocess.run(
            [LIBATION_EXE] + args, capture_output=True, text=True, encoding="utf-8"
        )
        if DEBUG and result.stderr:
            print(f"  [STDERR] {result.stderr}")
        return result.stdout.strip()


def get_books_folder():
    """Retrieves the physical path where Libation saves your audiobooks."""
    raw = run_cli(["get-setting", "Books", "-b"], capture=True)
    if DEBUG:
        print(f"  [get-setting output] {raw}")
    # Regex to handle Libation's specific output format and Windows path prefixes
    match = re.search(r'Books="(.*)"', raw)
    if match:
        path = match.group(1).replace("\\\\?\\", "").replace("\\?\\", "").rstrip("\\")
        return path
    # Fallback: maybe the output is just the path itself
    if raw and os.path.isdir(raw.replace("\\\\?\\", "").replace("\\?\\", "")):
        return raw.replace("\\\\?\\", "").replace("\\?\\", "")
    return None


def show_export_help():
    """Show the export command help to discover correct syntax."""
    print("\n--- Libation Export Help ---")
    run_cli(["export", "--help"])
    print("--- End Help ---\n")


def export_library_json(output_path):
    """
    Export library metadata to JSON. Tries multiple syntax variants
    since Libation CLI syntax varies by version.
    """
    # Remove existing file to ensure we detect fresh export
    if os.path.exists(output_path):
        os.remove(output_path)

    # Different export command syntaxes to try (Libation versions vary)
    export_attempts = [
        # Attempt 1: Simple syntax (most common)
        ["export", "--json", "-p", output_path],
        # Attempt 2: Modern syntax with all flags
        [
            "export",
            "--json",
            "-f",
            "--include-files",
            "--include-chapters",
            "-p",
            output_path,
        ],
        # Attempt 3: With account name positional
        ["export", "Audible", "--json", "-p", output_path],
        # Attempt 4: Output redirect style (path last, no -p)
        ["export", "--json", "--include-files", "--include-chapters", output_path],
        # Attempt 5: Bare minimum
        ["export", "-p", output_path],
    ]

    for i, args in enumerate(export_attempts, 1):
        print(f"\n  Trying export syntax #{i}: {' '.join(args)}")
        result = subprocess.run(
            [LIBATION_EXE] + args, capture_output=True, text=True, encoding="utf-8"
        )

        if result.stdout:
            print(f"  [STDOUT] {result.stdout[:500]}")
        if result.stderr:
            print(f"  [STDERR] {result.stderr[:500]}")

        # Check if file was created
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            print(f"  SUCCESS: JSON exported with syntax #{i}")
            return True
        else:
            print(f"  No file created with syntax #{i}")

    return False
