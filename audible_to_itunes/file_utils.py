"""File scanning, path resolution, and filename utilities."""

import os
import re


def sanitize_filename(name):
    """Remove characters that are invalid in Windows filenames."""
    return re.sub(r'[\\/*?:"<>|]', "", name)


def scan_m4b_files(base_folder):
    r"""
    Recursively scan the books folder to find all .m4b files.
    Returns (dict, count) where dict maps normalized search keys to file paths,
    and count is the actual number of unique .m4b files found.
    """
    m4b_files = {}
    file_count = 0
    for root, dirs, files in os.walk(base_folder):
        for filename in files:
            if filename.lower().endswith(".m4b"):
                full_path = os.path.join(root, filename)
                file_count += 1
                # Create multiple search keys for matching
                # Key by filename without extension
                name_key = os.path.splitext(filename)[0].lower()
                m4b_files[name_key] = full_path
                # Also key by the full relative path
                rel_path = os.path.relpath(full_path, base_folder).lower()
                m4b_files[rel_path] = full_path
    return m4b_files, file_count


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
