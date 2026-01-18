import json
import subprocess
import os
import re
import shutil
import sys

# --- CONFIGURATION ---
LIBATION_EXE = r"D:\OneDrive\System\Portable Apps\Libation\LibationCli.exe"
SPLIT_LIMIT_HRS = 10
SPLIT_LIMIT_SECS = SPLIT_LIMIT_HRS * 3600
OUTPUT_FOLDER = "iPod_Ready_Parts"
DEBUG = True  # Set to False in production to suppress CLI output
FILTER_BY_AUTHOR = ""  # To speed up testing, leave blank to process all books


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


def scan_m4b_files(base_folder):
    r"""
    Recursively scan the books folder to find all .m4b files.
    Returns a dict mapping normalized search keys to file paths.
    """
    m4b_files = {}
    for root, dirs, files in os.walk(base_folder):
        for filename in files:
            if filename.lower().endswith(".m4b"):
                full_path = os.path.join(root, filename)
                # Create multiple search keys for matching
                # Key by filename without extension
                name_key = os.path.splitext(filename)[0].lower()
                m4b_files[name_key] = full_path
                # Also key by the full relative path
                rel_path = os.path.relpath(full_path, base_folder).lower()
                m4b_files[rel_path] = full_path
    return m4b_files


def resolve_book_path(book, base_folder, m4b_cache):
    """
    Find the .m4b file path for a book by matching title/author.
    Since Libation v13 JSON doesn't include file paths, we search the folder.
    """
    title = book.get("Title", "")
    author = book.get("AuthorNames", "")
    asin = book.get("AudibleProductId", "")

    # Normalize for matching
    title_lower = title.lower()
    author_lower = author.lower() if author else ""
    safe_title = sanitize_filename(title).lower()

    # Try various matching strategies
    for key, path in m4b_cache.items():
        # Match by title in filename
        if title_lower in key or safe_title in key:
            return path
        # Match by ASIN in path
        if asin and asin.lower() in key:
            return path
        # Match if both author and title fragments appear in path
        if author_lower and title_lower:
            title_words = [w for w in title_lower.split() if len(w) > 3]
            author_words = [w for w in author_lower.split() if len(w) > 3]
            if any(w in key for w in title_words) and any(
                w in key for w in author_words
            ):
                return path

    return None


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


def perform_split(book, base_folder, m4b_cache):
    title = book.get("Title", "Unknown Title")
    safe_title = sanitize_filename(title)

    # 1. Find the .m4b file by searching the folder
    input_file = resolve_book_path(book, base_folder, m4b_cache)

    if not input_file:
        if DEBUG:
            print(f"  ! No .m4b file found for '{title}'")
        return

    if not os.path.exists(input_file):
        print(f"  ! File not found on disk: {input_file}")
        return

    # 2. Get actual duration from file (more accurate than JSON metadata)
    duration = get_duration_from_file(input_file)
    if duration == 0:
        # Fallback to JSON metadata
        duration = book.get("LengthInMinutes", 0) * 60

    if duration <= SPLIT_LIMIT_SECS:
        # Copy the file as-is (no split needed)
        output_name = os.path.join(OUTPUT_FOLDER, f"{safe_title}.m4b")
        if os.path.exists(output_name):
            print(f"  - Already exists: '{safe_title}' ({duration/3600:.1f}h)")
            return
        print(
            f"  - Copying '{title}' ({duration/3600:.1f}h, under {SPLIT_LIMIT_HRS}h - no split needed)"
        )
        shutil.copy2(input_file, output_name)
        size_mb = os.path.getsize(output_name) / (1024 * 1024)
        print(f"    Copied: {output_name} ({size_mb:.1f} MB)")
        return

    print(f"\n>>> PROCESSING: {title} ({duration/3600:.1f} hrs)")
    print(f"    Source: {input_file}")

    # 3. Get chapters directly from the file using FFprobe
    chapters = get_chapters_from_file(input_file)
    if not chapters:
        print("  ! No chapter metadata found in file. Splitting will be generic.")
    else:
        print(f"    Found {len(chapters)} chapters in file")

    current_start = 0
    part_num = 1

    while current_start < duration:
        target_split = current_start + SPLIT_LIMIT_SECS

        # Buffer: If less than 1 hour remains after a split, just take the whole thing
        if duration - current_start < (SPLIT_LIMIT_SECS * 1.1):
            end_time = duration
        else:
            # Split at the chapter closest to the 10-hour mark
            if chapters:
                best_chap = min(
                    chapters, key=lambda c: abs(c.get("StartOffset", 0) - target_split)
                )
                end_time = best_chap.get("StartOffset", 0)
                # Ensure we make progress (don't split at current_start)
                if end_time <= current_start:
                    end_time = target_split
            else:
                end_time = target_split

        part_label = f"Part {part_num}"
        output_name = os.path.join(OUTPUT_FOLDER, f"{safe_title} - {part_label}.m4b")

        print(
            f"  Creating {part_label} ({current_start/3600:.2f}h - {end_time/3600:.2f}h)..."
        )

        # 3. Audio Extraction (Lossless, strip existing chapters)
        temp_audio = "temp_chunk.m4b"
        ffmpeg_extract = [
            "ffmpeg",
            "-y",
            "-ss",
            str(current_start),
            "-to",
            str(end_time),
            "-i",
            input_file,
            "-map_chapters",
            "-1",  # Strip existing chapters from source
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            temp_audio,
        ]

        if DEBUG:
            print(f"    [FFmpeg Extract] {' '.join(ffmpeg_extract)}")
            result = subprocess.run(ffmpeg_extract, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"    [FFmpeg Error] {result.stderr[-500:]}")
        else:
            subprocess.run(ffmpeg_extract, capture_output=True)

        # 4. Generate Corrected Metadata (Offsetting Chapter Timestamps)
        meta_file = "temp_meta.txt"
        with open(meta_file, "w", encoding="utf-8") as f:
            f.write(";FFMETADATA1\n")
            f.write(f"title={title} - {part_label}\n")
            f.write(f"album={title}\n")

            # Handle different author field formats
            author = "Unknown"
            if book.get("AuthorNames"):
                author = (
                    book["AuthorNames"][0]
                    if isinstance(book["AuthorNames"], list)
                    else book["AuthorNames"]
                )
            elif book.get("Author"):
                author = book["Author"]
            f.write(f"artist={author}\n\n")

            # Filter chapters for this part and subtract current_start from their timestamps
            part_chapters = [
                c
                for c in chapters
                if current_start <= c.get("StartOffset", 0) < end_time
            ]

            for c in part_chapters:
                # Recalculate offsets so this part's chapters start at 0
                c_start_ms = int((c.get("StartOffset", 0) - current_start) * 1000)
                c_length_ms = int(c.get("LengthInSeconds", 60) * 1000)
                c_end_ms = c_start_ms + c_length_ms

                f.write("[CHAPTER]\n")
                f.write("TIMEBASE=1/1000\n")
                f.write(f"START={max(0, c_start_ms)}\n")
                f.write(f"END={c_end_ms}\n")
                f.write(f"title={c.get('Name', c.get('Title', 'Chapter'))}\n\n")

        # 5. Mux Audio + Metadata (apply our recalculated chapters)
        ffmpeg_mux = [
            "ffmpeg",
            "-y",
            "-i",
            temp_audio,
            "-i",
            meta_file,
            "-map_metadata",
            "1",  # Use metadata from our metadata file
            "-map_chapters",
            "1",  # Use chapters from our metadata file
            "-c",
            "copy",
            output_name,
        ]

        if DEBUG:
            print(f"    [FFmpeg Mux] {' '.join(ffmpeg_mux)}")
            result = subprocess.run(ffmpeg_mux, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"    [FFmpeg Error] {result.stderr[-500:]}")
        else:
            subprocess.run(ffmpeg_mux, capture_output=True)

        # Verify output was created
        if os.path.exists(output_name):
            size_mb = os.path.getsize(output_name) / (1024 * 1024)
            print(f"    Created: {output_name} ({size_mb:.1f} MB)")
        else:
            print(f"    WARNING: Failed to create {output_name}")

        # Cleanup temps
        if os.path.exists(temp_audio):
            os.remove(temp_audio)
        if os.path.exists(meta_file):
            os.remove(meta_file)

        current_start = end_time
        part_num += 1


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
        # Attempt 1: Modern syntax with all flags
        [
            "export",
            "--json",
            "-f",
            "--include-files",
            "--include-chapters",
            "-p",
            output_path,
        ],
        # Attempt 2: Simpler syntax - just json output to file
        ["export", "--json", "-p", output_path],
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


def sanitize_filename(name):
    """Remove characters that are invalid in Windows filenames."""
    return re.sub(r'[\\/*?:"<>|]', "", name)


if __name__ == "__main__":
    print("=" * 60)
    print("Audible to iPod Pipeline")
    print("=" * 60)

    # Verify Libation exists
    if not os.path.exists(LIBATION_EXE):
        print(f"ERROR: Libation not found at: {LIBATION_EXE}")
        print("Please update LIBATION_EXE path in the script.")
        sys.exit(1)

    # Setup output folder
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)

    # Show export help to understand available options
    if DEBUG:
        show_export_help()

    # Get books folder
    print("\nStep 1: Discovering Libation library folder...")
    folder = get_books_folder()
    if not folder:
        print("ERROR: Could not locate Libation 'Books' folder.")
        print("Make sure Libation is configured and has downloaded books.")
        sys.exit(1)

    print(f"  Library Folder: {folder}")
    if not os.path.isdir(folder):
        print(f"  WARNING: Folder does not exist or is inaccessible!")

    # Scan and Liberate
    print("\nStep 2: Syncing with Audible...")
    run_cli(["scan"])

    print("\nStep 3: Downloading/Decrypting missing books...")
    run_cli(["liberate"])

    # Export metadata
    print("\nStep 4: Exporting library metadata to JSON...")
    meta_json = os.path.abspath("library_data.json")

    if not export_library_json(meta_json):
        print("\nERROR: All export attempts failed!")
        print(
            "Please check LibationCli.exe export --help manually and update the script."
        )
        sys.exit(1)

    # Scan for .m4b files in the library folder
    print("\nStep 5: Scanning for .m4b files...")
    m4b_cache = scan_m4b_files(folder)
    print(f"  Found {len(m4b_cache)} .m4b file entries")

    if DEBUG and m4b_cache:
        sample_files = list(set(m4b_cache.values()))[:5]
        for f in sample_files:
            print(f"    - {f}")

    # Load and process books
    print("\nStep 6: Processing books...")
    try:
        with open(meta_json, "r", encoding="utf-8") as f:
            content = f.read()
            books_list = json.loads(content)
    except json.JSONDecodeError as e:
        print(f"ERROR: Failed to parse JSON: {e}")
        print("The exported file may not be valid JSON. Check its contents.")
        sys.exit(1)

    # Filter to liberated books only
    liberated_books = [b for b in books_list if b.get("BookStatus") == "Liberated"]
    liberated_books = [
        b for b in liberated_books if FILTER_BY_AUTHOR in b.get("AuthorNames", "")
    ]
    long_books = [
        b
        for b in liberated_books
        if b.get("LengthInMinutes", 0) * 60 > SPLIT_LIMIT_SECS
    ]

    print(f"  Loaded {len(books_list)} books total")
    print(
        f"  Found {len(liberated_books)} liberated books ({len(long_books)} > {SPLIT_LIMIT_HRS}h need splitting)"
    )

    processed = 0
    for book in liberated_books:
        perform_split(book, folder, m4b_cache)
        processed += 1

    if processed == 0:
        print(f"  No liberated books found.")

    # Cleanup
    if os.path.exists(meta_json) and not DEBUG:
        os.remove(meta_json)
    elif DEBUG:
        print(f"\n  [DEBUG] Keeping {meta_json} for inspection")

    print("\n" + "=" * 60)
    print(f"Complete! iPod-ready files are in: {os.path.abspath(OUTPUT_FOLDER)}")
    print("=" * 60)
