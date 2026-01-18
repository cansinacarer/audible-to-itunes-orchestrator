"""Configuration management - loads settings from environment variables."""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- CONFIGURATION (from .env or defaults) ---
LIBATION_EXE = os.getenv(
    "LIBATION_EXE", r"D:\OneDrive\System\Portable Apps\Libation\LibationCli.exe"
)
SPLIT_LIMIT_HRS = int(os.getenv("SPLIT_LIMIT_HRS", "10"))
SPLIT_LIMIT_SECS = SPLIT_LIMIT_HRS * 3600
OUTPUT_FOLDER = os.getenv("OUTPUT_FOLDER", "iPod_Ready_Parts")
DEBUG = os.getenv("DEBUG", "True").lower() in ("true", "1", "yes")
FILTER_BY_AUTHOR = os.getenv("FILTER_BY_AUTHOR", "")  # Leave blank to process all books
