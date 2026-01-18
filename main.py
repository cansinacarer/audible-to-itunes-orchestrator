#!/usr/bin/env python3
"""
Audible to iTunes Orchestrator

Entry point for the audiobook processing pipeline.
Can be run directly or via: python -m audible_to_itunes
"""

from audible_to_itunes.orchestrator import main

if __name__ == "__main__":
    main()
