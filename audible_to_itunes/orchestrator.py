"""Main orchestration logic for the Audible to iTunes pipeline."""

import json
import os
import sys

from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from .config import (
    DEBUG,
    FILTER_BY_AUTHOR,
    LIBATION_EXE,
    OUTPUT_FOLDER,
    SPLIT_LIMIT_HRS,
    SPLIT_LIMIT_SECS,
)
from .console import console
from .file_utils import scan_m4b_files
from .libation import (
    export_library_json,
    get_books_folder,
    run_cli,
    show_export_help,
)
from .processing_state import processing_state, setup_signal_handlers
from .splitter import perform_split


def main():
    """Main entry point for the Audible to iPod pipeline."""
    # Register signal handlers for graceful shutdown
    setup_signal_handlers()

    print("=" * 60)
    print("Audible to iPod Pipeline")
    print("=" * 60)
    print(f"\nConfiguration:")
    print(f"  LIBATION_EXE:    {LIBATION_EXE}")
    print(f"  OUTPUT_FOLDER:   {OUTPUT_FOLDER}")
    print(f"  SPLIT_LIMIT_HRS: {SPLIT_LIMIT_HRS}")
    if FILTER_BY_AUTHOR:
        print(f"  FILTER_BY_AUTHOR: {FILTER_BY_AUTHOR}")

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
    m4b_cache, m4b_count = scan_m4b_files(folder)
    print(f"  Found {m4b_count} .m4b files")

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
    if FILTER_BY_AUTHOR:
        liberated_books = [
            b
            for b in liberated_books
            if FILTER_BY_AUTHOR.lower() in b.get("AuthorNames", "").lower()
        ]
    long_books = [
        b
        for b in liberated_books
        if b.get("LengthInMinutes", 0) * 60 > SPLIT_LIMIT_SECS
    ]

    console.print(f"  Loaded {len(books_list)} books total")
    console.print(
        f"  Found {len(liberated_books)} liberated books ({len(long_books)} > {SPLIT_LIMIT_HRS}h need splitting)"
    )

    if len(liberated_books) == 0:
        console.print("  No liberated books found.")
    else:
        _process_books(liberated_books, folder, m4b_cache)

    # Cleanup
    if os.path.exists(meta_json) and not DEBUG:
        os.remove(meta_json)
    elif DEBUG:
        console.print(f"\n  [DEBUG] Keeping {meta_json} for inspection")

    console.print("\n" + "=" * 60)
    if processing_state.stop_requested:
        console.print(
            f"[yellow]Stopped![/yellow] Processed files are in: {os.path.abspath(OUTPUT_FOLDER)}"
        )
    else:
        console.print(
            f"Complete! iPod-ready files are in: {os.path.abspath(OUTPUT_FOLDER)}"
        )
    console.print("=" * 60)


def _process_books(liberated_books, folder, m4b_cache):
    """Process all liberated books with progress tracking."""
    completed = 0
    failed = 0
    skipped = 0
    total = len(liberated_books)
    failed_books = []  # Track names of failed books

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("[cyan]{task.fields[status]}"),
        TimeElapsedColumn(),
        console=console,
        refresh_per_second=4,
    ) as progress:
        # Main task for overall book progress
        main_task = progress.add_task(
            "[green]Processing books...",
            total=total,
            status=f"0/{total} books done, 0 failed, 0 skipped",
        )
        # Secondary task for current book progress (parts)
        book_task = progress.add_task(
            "[dim]Waiting...",
            total=1,
            visible=True,
            status="",
        )

        stopped_early = False
        for book in liberated_books:
            # Check if stop was requested before starting next book
            if processing_state.stop_requested:
                stopped_early = True
                break

            title = book.get("Title", "Unknown")[:40]
            progress.update(main_task, description=f"[green]{title}")
            progress.update(
                book_task, completed=0, total=1, description="[yellow]Starting..."
            )

            # Use console.print as log function so output appears above progress bar
            result = perform_split(
                book,
                folder,
                m4b_cache,
                log=console.print,
                progress=progress,
                book_task=book_task,
            )

            if result == "success":
                completed += 1
            elif result == "failed":
                failed += 1
                failed_books.append(book.get("Title", "Unknown"))
            elif result == "skipped":
                skipped += 1
                completed += 1  # Skipped counts as completed (already exists)
            elif result == "stopped":
                stopped_early = True
                break

            progress.update(
                main_task,
                advance=1,
                status=f"{completed}/{total} books done, {failed} failed, {skipped} skipped",
            )

        if stopped_early:
            progress.update(main_task, description="[yellow]Stopped by user")
        else:
            progress.update(main_task, description="[green]Complete!")
        progress.update(book_task, visible=False)

    # Print summary of failed books
    if failed_books:
        console.print(
            f"\n[red]Failed to process {len(failed_books)} book(s):[/red]"
        )
        for title in failed_books:
            console.print(f"  [red]- {title}[/red]")
        console.print(
            "[dim]Partial output files have been deleted. These books will be retried on next run.[/dim]"
        )

    # Print stop message
    if stopped_early:
        remaining = total - (completed + failed - skipped)
        console.print(
            f"\n[yellow]Stopped early. {remaining} book(s) were not processed.[/yellow]"
        )
        console.print("[dim]Run again to continue where you left off.[/dim]")
