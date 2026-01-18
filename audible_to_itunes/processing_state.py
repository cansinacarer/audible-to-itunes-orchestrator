"""Processing state management for graceful shutdown handling."""

import os
import signal
import sys

from .console import console


class ProcessingState:
    """Track current processing state for graceful shutdown."""

    def __init__(self):
        self.stop_requested = False
        self.current_book_title = None
        self.current_book_files = []  # Completed files for current book
        self.in_progress_files = []  # Files currently being written (temp + output)
        self.current_process = None  # Current running subprocess

    def request_stop(self):
        self.stop_requested = True

    def start_book(self, title):
        self.current_book_title = title
        self.current_book_files = []
        self.in_progress_files = []

    def add_file(self, filepath):
        """Mark a file as successfully completed."""
        self.current_book_files.append(filepath)
        # Remove from in-progress if it was there
        if filepath in self.in_progress_files:
            self.in_progress_files.remove(filepath)

    def start_file(self, filepath):
        """Track a file that's about to be written (for cleanup if interrupted)."""
        if filepath not in self.in_progress_files:
            self.in_progress_files.append(filepath)

    def finish_file(self, filepath):
        """Remove a file from in-progress tracking (called on success or explicit cleanup)."""
        if filepath in self.in_progress_files:
            self.in_progress_files.remove(filepath)

    def set_process(self, proc):
        """Track current subprocess so we can kill it on stop."""
        self.current_process = proc

    def kill_current_process(self):
        """Kill the current running subprocess if any."""
        if self.current_process:
            try:
                self.current_process.terminate()
                self.current_process.wait(timeout=2)
            except Exception:
                try:
                    self.current_process.kill()
                except Exception:
                    pass
            self.current_process = None

    def cleanup_in_progress(self):
        """Delete any files currently being written (called immediately on stop)."""
        for f in self.in_progress_files[:]:  # Copy list since we modify it
            try:
                if os.path.exists(f):
                    os.remove(f)
                    console.print(f"  [dim]Deleted in-progress: {f}[/dim]")
            except OSError as e:
                console.print(f"  [red]Failed to delete {f}: {e}[/red]")
        self.in_progress_files = []

    def cleanup_current_book(self):
        """Delete all partial files from current book (in-progress + completed)."""
        # First clean up any in-progress files
        self.cleanup_in_progress()

        # Then clean up completed files for this book
        if self.current_book_files:
            console.print(
                f"\n[yellow]Cleaning up partial files for '{self.current_book_title}'...[/yellow]"
            )
            for f in self.current_book_files:
                try:
                    if os.path.exists(f):
                        os.remove(f)
                        console.print(f"  [dim]Deleted: {f}[/dim]")
                except OSError as e:
                    console.print(f"  [red]Failed to delete {f}: {e}[/red]")
            self.current_book_files = []


# Global processing state
processing_state = ProcessingState()


def _signal_handler(signum, frame):
    """Handle Ctrl+C - immediately stop and cleanup."""
    if processing_state.stop_requested:
        # Second Ctrl+C - force exit
        console.print("\n[red]Force quit![/red]")
        sys.exit(1)

    console.print(
        "\n[yellow]Stop requested (Ctrl+C). Cancelling and cleaning up...[/yellow]"
    )

    # Kill any running process immediately
    processing_state.kill_current_process()

    # Immediately clean up any files that were being written
    processing_state.cleanup_in_progress()

    console.print("[dim]Press Ctrl+C again to force quit.[/dim]")
    processing_state.request_stop()


def setup_signal_handlers():
    """Register signal handlers for graceful shutdown."""
    signal.signal(signal.SIGINT, _signal_handler)
