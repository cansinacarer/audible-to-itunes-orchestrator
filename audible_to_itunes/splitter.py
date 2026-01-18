"""Main audiobook splitting logic."""

import os
import shutil

from .config import DEBUG, OUTPUT_FOLDER, SPLIT_LIMIT_HRS, SPLIT_LIMIT_SECS
from .ffmpeg import get_chapters_from_file, get_duration_from_file, run_ffmpeg
from .file_utils import resolve_book_path, sanitize_filename
from .processing_state import processing_state


def perform_split(
    book, base_folder, m4b_cache, log=print, progress=None, book_task=None
):
    """
    Process a book: copy if short, split if long.
    Returns: "success", "failed", "skipped", or "stopped"

    If progress and book_task are provided, updates the progress bar for this book.
    """
    title = book.get("Title", "Unknown Title")
    safe_title = sanitize_filename(title)

    # Track this book for graceful shutdown
    processing_state.start_book(title)

    # 1. Find the .m4b file by searching the folder
    input_file = resolve_book_path(book, base_folder, m4b_cache)

    if not input_file:
        if DEBUG:
            log(f"  ! No .m4b file found for '{title}'")
        return "failed"

    if not os.path.exists(input_file):
        log(f"  ! File not found on disk: {input_file}")
        return "failed"

    # 2. Get actual duration from file (more accurate than JSON metadata)
    duration = get_duration_from_file(input_file)
    if duration == 0:
        # Fallback to JSON metadata
        duration = book.get("LengthInMinutes", 0) * 60

    # Copy if under limit, or within 10% buffer (would only be 1 part anyway)
    if duration <= SPLIT_LIMIT_SECS * 1.1:
        # Copy the file as-is (no split needed)
        output_name = os.path.join(OUTPUT_FOLDER, f"{safe_title}.m4b")
        if os.path.exists(output_name):
            log(f"  - Already exists: '{safe_title}' ({duration/3600:.1f}h)")
            if progress and book_task is not None:
                progress.update(book_task, total=1, completed=1)
            return "skipped"
        log(
            f"  - Copying '{title}' ({duration/3600:.1f}h - no split needed)"
        )
        if progress and book_task is not None:
            progress.update(
                book_task,
                total=1,
                completed=0,
                description="[yellow]Copying...",
                status="0/1 parts done",
            )

        # Track file BEFORE copying so it gets cleaned up if interrupted
        processing_state.start_file(output_name)
        try:
            shutil.copy2(input_file, output_name)
            processing_state.finish_file(output_name)  # Successfully completed
        except Exception as e:
            # Clean up partial file on any error
            processing_state.finish_file(output_name)
            if os.path.exists(output_name):
                os.remove(output_name)
            if processing_state.stop_requested:
                return "stopped"
            raise

        if processing_state.stop_requested:
            # Copy completed but stop was requested - clean it up
            if os.path.exists(output_name):
                os.remove(output_name)
            return "stopped"

        size_mb = os.path.getsize(output_name) / (1024 * 1024)
        log(f"    Copied: {output_name} ({size_mb:.1f} MB)")
        if progress and book_task is not None:
            progress.update(
                book_task,
                completed=1,
                description="[green]Done",
                status="1/1 parts done",
            )
        return "success"

    # Calculate total parts for progress tracking
    # Must match the actual splitting logic which combines parts if <10% buffer remains
    def calc_actual_parts(dur, limit):
        parts = 0
        pos = 0
        while pos < dur:
            # Same logic as the splitting: if less than 110% of limit remains, take it all
            if dur - pos < (limit * 1.1):
                parts += 1
                break
            else:
                parts += 1
                pos += limit
        return max(1, parts)

    total_parts = calc_actual_parts(duration, SPLIT_LIMIT_SECS)

    # Check if all parts already exist (skip if fully processed)
    all_parts_exist = True
    for i in range(1, total_parts + 1):
        part_file = os.path.join(OUTPUT_FOLDER, f"{safe_title} - Part {i}.m4b")
        if not os.path.exists(part_file):
            all_parts_exist = False
            break

    if all_parts_exist:
        log(f"  - Already exists: '{safe_title}' ({total_parts} parts)")
        if progress and book_task is not None:
            progress.update(book_task, total=1, completed=1)
        return "skipped"

    if progress and book_task is not None:
        progress.update(
            book_task,
            total=total_parts,
            completed=0,
            description=f"[yellow]Splitting into {total_parts} parts...",
            status=f"0/{total_parts} parts done",
        )

    log(f"\n>>> PROCESSING: {title} ({duration/3600:.1f} hrs) -> {total_parts} parts")
    log(f"    Source: {input_file}")

    # 3. Get chapters directly from the file using FFprobe
    chapters = get_chapters_from_file(input_file)
    if not chapters:
        log("  ! No chapter metadata found in file. Splitting will be generic.")
    else:
        log(f"    Found {len(chapters)} chapters in file")

    all_parts_created = True
    created_files = []  # Track files created so we can delete on failure

    current_start = 0
    part_num = 1

    while current_start < duration:
        # Check for graceful stop request
        if processing_state.stop_requested:
            log(f"  [yellow]Stop requested - aborting '{title}'[/yellow]")
            # Clean up partial files
            for f in created_files:
                try:
                    if os.path.exists(f):
                        os.remove(f)
                        log(f"    Deleted: {f}")
                except OSError:
                    pass
            processing_state.current_book_files = []
            return "stopped"

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

        log(
            f"  Creating {part_label} ({current_start/3600:.2f}h - {end_time/3600:.2f}h)..."
        )

        # Define temp file names before try block for safe cleanup
        temp_audio = "temp_chunk.m4b"
        meta_file = "temp_meta.txt"

        # Track all files we're about to write so they get cleaned up if interrupted
        processing_state.start_file(temp_audio)
        processing_state.start_file(meta_file)
        processing_state.start_file(output_name)

        try:
            # 3. Audio Extraction (Lossless, strip existing chapters)
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
                log(f"    [FFmpeg Extract] {' '.join(ffmpeg_extract)}")

            success, _ = run_ffmpeg(ffmpeg_extract, log)
            if not success:
                if processing_state.stop_requested:
                    raise InterruptedError("Stop requested")
                all_parts_created = False

            # 4. Generate Corrected Metadata (Offsetting Chapter Timestamps)
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
                log(f"    [FFmpeg Mux] {' '.join(ffmpeg_mux)}")

            success, _ = run_ffmpeg(ffmpeg_mux, log)
            if not success:
                if processing_state.stop_requested:
                    raise InterruptedError("Stop requested")
                all_parts_created = False

            # Verify output was created
            if os.path.exists(output_name):
                size_mb = os.path.getsize(output_name) / (1024 * 1024)
                log(f"    Created: {output_name} ({size_mb:.1f} MB)")
                created_files.append(output_name)
                processing_state.add_file(output_name)  # Mark as complete, remove from in-progress
            else:
                log(f"    WARNING: Failed to create {output_name}")
                all_parts_created = False

        except InterruptedError:
            # Stop was requested - cleanup and exit
            log(f"  [yellow]Cancelled {part_label}[/yellow]")
            all_parts_created = False
            # Clean up any partial output file (in-progress files already cleaned by signal handler)
            if os.path.exists(output_name):
                try:
                    os.remove(output_name)
                except OSError:
                    pass
            break  # Exit the while loop

        except Exception as e:
            log(f"    [red]ERROR processing {part_label}: {e}[/red]")
            all_parts_created = False

        finally:
            # Cleanup temps and remove from tracking
            for temp_file in [temp_audio, meta_file]:
                processing_state.finish_file(temp_file)
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except OSError:
                        pass
            # Remove output from in-progress tracking (either completed or failed)
            processing_state.finish_file(output_name)

        # Update book-level progress
        if progress and book_task is not None:
            progress.update(
                book_task,
                advance=1,
                description=f"[yellow]Part {part_num}/{total_parts}",
                status=f"{part_num}/{total_parts} parts done",
            )

        current_start = end_time
        part_num += 1

    # If stopped or failed, clean up partial files
    if not all_parts_created or processing_state.stop_requested:
        if created_files:
            log(f"  ! Cleaning up partial files for '{title}'...")
            for f in created_files:
                try:
                    if os.path.exists(f):
                        os.remove(f)
                        log(f"    Deleted: {f}")
                except OSError as e:
                    log(f"    Failed to delete {f}: {e}")
        processing_state.current_book_files = []

        if processing_state.stop_requested:
            return "stopped"
        return "failed"

    if progress and book_task is not None:
        progress.update(
            book_task,
            description="[green]Done",
            status=f"{total_parts}/{total_parts} parts done",
        )

    return "success"
