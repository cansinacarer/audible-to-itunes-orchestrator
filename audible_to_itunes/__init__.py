"""
Audible to iTunes Orchestrator

A tool for processing Audible audiobooks via Libation for iTunes/iPod compatibility.
Handles syncing, decrypting, and splitting long audiobooks into smaller parts.
"""

__version__ = "1.0.0"

from .orchestrator import main

__all__ = ["main"]
