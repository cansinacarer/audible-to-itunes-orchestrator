# Audible to iTunes Orchestrator

## Problem

iPod Classic, even the 7th gen, struggles playing single file audiobooks longer than 12-13 hours without a compromise in bitrate. I don't like creating a file for each chapter, which clutters my library. So I had to have my audiobooks split into fewest parts possible.

I built this iPod classic with a Bluetooth screen and MagSafe charging with [my custom design](https://www.thingiverse.com/thing:7272815), but could't play my Audiobooks properly 😕

<img width="300px" src="https://cdn.thingiverse.com/assets/23/22/64/dc/20/large_display_combined-hero.png">

## Existing Solutions That Didn't Work Out (like a literature review 😂)

- [Libation](https://github.com/rmcrackan/Libation) is the best solution I've found, but it can either create one file per chapter, or one file per book. You cannot specify the length you want per file.
- [AaxAudioConverter](https://github.com/audiamus/AaxAudioConverter) can embed chapter names into split books, but you have to give it a metadata file with chapter name and timings.
- [BookLibConnect](https://github.com/audiamus/BookLibConnect) can download metadata for a single file book, but fails on multi-part downloads because Audible is deprecating it.
- Custom split with ffmpeg only works if you make a custom metadata file with chapter timings offsets for your split files.

## My Solution

I wrote this script to:

- Make Libation download the books via its CLI,
- Split them into <10 hours long files, if needed,
  - with chapter names preserved and correctly embedded on separated files,
  - without splitting mid-chapter,
  - naming each file with part numbers.

## Getting Started

1. Install [Libation](https://github.com/rmcrackan/Libation) and configure it to work with your Audible account,
2. Configure the path of your Libation CLI in `main.py`,
3. Run main.py with `uv run main.py`.

It will find the books in the library folder you configured in Libation, make Libation download the new books you purchased, then split the downloaded books with correct metadata and chapter names embedded.

You can then add the output folder of this script into your iTunes library.