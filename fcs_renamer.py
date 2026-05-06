#!/usr/bin/env python3
"""
FCS Renamer
===========
Renames the $FIL keyword in FCS file TEXT segments.

Modes:
  1. Filename mode  – set $FIL to the file's own filename (default)
  2. CSV mode       – supply a CSV mapping old→new names

Usage examples
--------------
  # Rename $FIL to filename for every .fcs in a folder
  python fcs_renamer.py /path/to/fcs/folder

  # Dry-run (preview, no writes)
  python fcs_renamer.py /path/to/fcs/folder --dry-run

  # Use a CSV mapping  (columns: filename, new_name)
  python fcs_renamer.py /path/to/fcs/folder --csv mapping.csv

  # Single file
  python fcs_renamer.py sample.fcs

  # Write renamed copies to a different directory
  python fcs_renamer.py /path/to/fcs/folder --output /path/to/output

CSV format (header row required):
  filename,new_name
  sample01.fcs,Patient_001_T0
  sample02.fcs,Patient_001_T1
"""

import argparse
import csv
import os
import re
import shutil
import struct
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# FCS low-level helpers
# ---------------------------------------------------------------------------

def _read_offsets(data: bytes):
    """Parse HEADER block and return (text_start, text_end, data_start, data_end)."""
    header = data[:58].decode("latin-1")
    version    = header[:6].strip()
    if not version.startswith("FCS"):
        raise ValueError("Not an FCS file (magic bytes missing)")
    text_start = int(header[10:18].strip())
    text_end   = int(header[18:26].strip())
    data_start = int(header[26:34].strip())
    data_end   = int(header[34:42].strip())
    return text_start, text_end, data_start, data_end


def _parse_text(raw: bytes):
    """
    Parse the TEXT segment into an ordered list of (key, value) pairs and
    return (delimiter, pairs).
    """
    delimiter = chr(raw[0])
    # Split on delimiter; first and last fields are empty because the segment
    # starts and ends with the delimiter.
    parts = raw.decode("latin-1").split(delimiter)
    # parts[0] is '' (before first delimiter), parts[-1] may be '' too
    parts = parts[1:]  # drop leading empty
    if len(parts) % 2 != 0:
        parts = parts[:-1]  # drop trailing empty/odd element
    pairs = [(parts[i], parts[i + 1]) for i in range(0, len(parts), 2)]
    return delimiter, pairs


def _build_text(delimiter: str, pairs: list) -> bytes:
    """Serialise key/value pairs back into a TEXT segment byte string."""
    body = delimiter + delimiter.join(k + delimiter + v for k, v in pairs) + delimiter
    return body.encode("latin-1")


def _update_fil(data: bytes, new_fil: str) -> bytes:
    """
    Return a new FCS byte string with the $FIL keyword replaced by *new_fil*.
    The header offsets are updated if the TEXT segment length changes.
    """
    text_start, text_end, data_start, data_end = _read_offsets(data)
    raw_text = data[text_start : text_end + 1]

    delimiter, pairs = _parse_text(raw_text)

    # Replace $FIL (case-insensitive)
    updated = False
    new_pairs = []
    for k, v in pairs:
        if k.upper() == "$FIL":
            new_pairs.append((k, new_fil))
            updated = True
        else:
            new_pairs.append((k, v))

    if not updated:
        # $FIL not present – insert it after $TOT or at position 1
        new_pairs.insert(1, ("$FIL", new_fil))

    new_raw_text = _build_text(delimiter, new_pairs)

    old_len = len(raw_text)
    new_len = len(new_raw_text)
    diff    = new_len - old_len

    # Rebuild file
    new_data = bytearray(data)

    if diff == 0:
        # In-place replacement
        new_data[text_start : text_end + 1] = new_raw_text
    else:
        # TEXT segment size changed – splice and update header
        new_data = bytearray(data[:text_start]) + bytearray(new_raw_text) + bytearray(data[text_end + 1:])

        new_text_end   = text_end   + diff
        new_data_start = data_start + diff if data_start > text_end else data_start
        new_data_end   = data_end   + diff if data_end   > text_end else data_end

        def _fmt(n): return f"{n:>8}".encode("latin-1")
        new_data[10:18] = _fmt(text_start)
        new_data[18:26] = _fmt(new_text_end)
        new_data[26:34] = _fmt(new_data_start)
        new_data[34:42] = _fmt(new_data_end)

    return bytes(new_data)


def _read_fil(data: bytes) -> str:
    """Return the current $FIL value, or '' if absent."""
    text_start, text_end, _, _ = _read_offsets(data)
    raw_text = data[text_start : text_end + 1]
    _, pairs = _parse_text(raw_text)
    for k, v in pairs:
        if k.upper() == "$FIL":
            return v
    return ""


# ---------------------------------------------------------------------------
# High-level rename logic
# ---------------------------------------------------------------------------

def rename_fcs(src: Path, new_fil: str, dest: Path, dry_run: bool) -> str:
    """
    Read *src*, update $FIL to *new_fil*, write to *dest*.
    Returns a status string.
    """
    data = src.read_bytes()
    old_fil = _read_fil(data)

    if old_fil == new_fil and src == dest:
        return f"  [SKIP]  {src.name}  ($FIL already '{new_fil}')"

    if dry_run:
        return f"  [DRY]   {src.name}  $FIL: '{old_fil}' → '{new_fil}'"

    new_data = _update_fil(data, new_fil)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(new_data)
    return f"  [OK]    {src.name}  $FIL: '{old_fil}' → '{new_fil}'"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def collect_fcs_files(path: Path) -> list:
    """Return a sorted list of .fcs files under *path* (file or directory)."""
    if path.is_file():
        if path.suffix.lower() != ".fcs":
            raise ValueError(f"'{path}' is not an .fcs file")
        return [path]
    return sorted(path.rglob("*.fcs"))


def load_csv_mapping(csv_path: Path) -> dict:
    """
    Load CSV file into {filename: new_name} dict.
    Expected columns: filename, new_name  (header row required)
    """
    mapping = {}
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        required = {"filename", "new_name"}
        if not required.issubset({c.lower() for c in reader.fieldnames or []}):
            raise ValueError(
                f"CSV must have columns 'filename' and 'new_name'. "
                f"Found: {reader.fieldnames}"
            )
        # normalise column names to lower-case
        for row in reader:
            row_lower = {k.lower(): v for k, v in row.items()}
            fname = row_lower["filename"].strip()
            nname = row_lower["new_name"].strip()
            if fname and nname:
                mapping[fname] = nname
    return mapping


def main():
    parser = argparse.ArgumentParser(
        description="Rename the $FIL keyword inside FCS files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "input",
        metavar="INPUT",
        help="FCS file or folder containing FCS files",
    )
    parser.add_argument(
        "--csv",
        metavar="CSV_FILE",
        help="CSV mapping file with columns 'filename' and 'new_name'",
    )
    parser.add_argument(
        "--output", "-o",
        metavar="OUTPUT_DIR",
        help="Directory for renamed copies (default: overwrite in-place)",
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Preview changes without writing any files",
    )
    args = parser.parse_args()

    input_path  = Path(args.input).resolve()
    output_dir  = Path(args.output).resolve() if args.output else None
    dry_run     = args.dry_run

    # ---- collect files ----
    try:
        fcs_files = collect_fcs_files(input_path)
    except ValueError as e:
        sys.exit(f"Error: {e}")

    if not fcs_files:
        sys.exit("No .fcs files found.")

    print(f"Found {len(fcs_files)} FCS file(s).")

    # ---- optional CSV mapping ----
    mapping = {}
    if args.csv:
        try:
            mapping = load_csv_mapping(Path(args.csv))
            print(f"Loaded {len(mapping)} mapping(s) from CSV.")
        except (ValueError, FileNotFoundError) as e:
            sys.exit(f"CSV error: {e}")

    # ---- process each file ----
    ok = skip = error = 0
    for src in fcs_files:
        # Determine new $FIL value
        if mapping:
            new_fil = mapping.get(src.name)
            if new_fil is None:
                print(f"  [SKIP]  {src.name}  (not in CSV mapping)")
                skip += 1
                continue
        else:
            new_fil = src.name   # use the filename itself

        # Determine destination path
        if output_dir:
            # Preserve sub-folder structure relative to input root
            try:
                rel = src.relative_to(input_path if input_path.is_dir() else input_path.parent)
            except ValueError:
                rel = Path(src.name)
            dest = output_dir / rel
        else:
            dest = src   # overwrite

        try:
            msg = rename_fcs(src, new_fil, dest, dry_run)
            print(msg)
            if "[SKIP]" in msg:
                skip += 1
            else:
                ok += 1
        except Exception as e:
            print(f"  [ERROR] {src.name}  {e}")
            error += 1

    # ---- summary ----
    print()
    print("=" * 50)
    mode = "DRY-RUN – no files written" if dry_run else "Done"
    print(f"{mode}: {ok} renamed, {skip} skipped, {error} error(s).")


if __name__ == "__main__":
    main()
