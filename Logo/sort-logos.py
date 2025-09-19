#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Korte-Hoffmann | Logo sorter & ZIPper
- Two modes: sort from .sort (then ZIP) or crawl/repair & ZIP only
- Skips OS metadata like .DS_Store / Thumbs.db / desktop.ini
- Processes only: .jpg .png .svg .pdf
- Normalizes filenames: umlauts -> ae/oe/ue/ss, spaces -> -, lowercase
  (keeps '+' as-is for 'architekten+ingenieure')
- “dreihaus” -> belongs to KH-Gebaeudedruck
- Favicons/Monogram go under brand/Favicons
- Folders: Size=L|M|S / Color=White|Black|White+Accent|Black+Accent / Trademark=Yes|No
- Cleaning rules:
  * size S AND trademark=yes -> delete
  * any WHITE + JPG -> delete
  * brand in {KORTE-HOFFMANN, KH-Gruppe} AND color in {white+accent, black+accent} -> delete
- After sorting: crawl directory to build ZIPs per-variant and per-brand
"""

import argparse
import os
import re
import sys
import shutil
import zipfile
from collections import defaultdict
from datetime import datetime

# ------------------------- Logging helpers -------------------------

def ts():
    return datetime.now().strftime("%H:%M:%S")

def log(level, msg):
    print(f"[{ts()}][{level}] {msg}", flush=True)

def info(msg): log("INF", msg)
def dbg(msg):  print(f"[{ts()}][DBG] {msg}", flush=True)
def warn(msg): log("WRN", msg)
def err(msg):  log("ERR", msg)

# ------------------------- Config -------------------------

BRAND_CANON = [
    "KH-Architekten+Ingenieure",
    "KH-Gebaeudedruck",
    "KH-Gruppe",
    "KH-Immobilien",
    "KORTE-HOFFMANN",
]

COLOR_CANON = [
    "white",
    "black",
    "white+accent",
    "black+accent",
]

SIZE_CANON = ["l", "m", "s"]

TRADEMARK_CANON = ["yes", "no"]

ALLOWED_EXTS = {".jpg", ".png", ".svg", ".pdf"}

SKIP_FILES = {"thumbs.db", "desktop.ini"}

# ------------------------- Normalization -------------------------

UMLAUT_MAP = {
    "ä":"ae","Ä":"ae",
    "ö":"oe","Ö":"oe",
    "ü":"ue","Ü":"ue",
    "ß":"ss",
}

def de_umlaut(s: str) -> str:
    for k, v in UMLAUT_MAP.items():
        s = s.replace(k, v)
    return s

def normalize_stem(stem: str) -> str:
    """
    Normalize only the stem (no extension):
    - umlauts
    - special handling 'architekten + ingenieure' -> 'architekten+ingenieure'
    - keep '+' (do NOT make '-+-')
    - spaces -> '-'
    - lowercase, collapse duplicate '-'
    """
    name = de_umlaut(stem).strip()

    pat_ai = re.compile(r"architekten\s*\+\s*ingenieure", re.IGNORECASE)
    name = pat_ai.sub("architekten+ingenieure", name)

    name = name.lower()
    name = re.sub(r"\s+", "-", name)
    name = re.sub(r"-{2,}", "-", name)
    return name

# ------------------------- Brand detection -------------------------

def detect_brand_from_name(name: str) -> str | None:
    n = name.lower()
    if "dreihaus" in n:
        return "KH-Gebaeudedruck"
    if any(k in n for k in ["gebaeudedruck", "gebäudedruck", "gebauudedruck"]):
        return "KH-Gebaeudedruck"
    if "immobilien" in n:
        return "KH-Immobilien"
    if "architekten+ingenieure" in n or re.search(r"architekten\s*\+\s*ingenieure", n):
        return "KH-Architekten+Ingenieure"
    if "gruppe" in n or "group" in n:
        return "KH-Gruppe"
    if any(k in n for k in ["korte-hoffmann","korte hoffmann","korte_hoffmann","kortehoffmann","kortehoffman","korte-hoffman"]):
        return "KORTE-HOFFMANN"
    return None

def ensure_brand_root(base_dir: str, brand: str) -> str:
    existing = {d.lower(): d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))}
    # Prefer existing casing if present
    if brand.lower() in existing:
        return os.path.join(base_dir, existing[brand.lower()])
    # Otherwise create the canon one
    path = os.path.join(base_dir, brand)
    os.makedirs(path, exist_ok=True)
    return path

# ------------------------- Variant parsing -------------------------

def parse_tokens(name_no_ext: str):
    n = name_no_ext
    size = None
    if re.search(r"(^|[_\-])s($|[_\-])", n): size = "s"
    if re.search(r"(^|[_\-])m($|[_\-])", n): size = "m"
    if re.search(r"(^|[_\-])l($|[_\-])", n): size = "l"

    tm = None
    if "no-trademark" in n: tm = "no"
    elif "trademark" in n:  tm = "yes"

    color = None
    if "white+accent" in n: color = "white+accent"
    elif "black+accent" in n: color = "black+accent"
    elif "white" in n: color = "white"
    elif "black" in n: color = "black"

    return size, tm, color

def is_favicon(name_no_ext: str) -> bool:
    return ("favicon" in name_no_ext) or ("monogram" in name_no_ext)

# ------------------------- Cleaning rules -------------------------

def should_delete(brand: str | None, size: str | None, tm: str | None, color: str | None, ext: str, name_no_ext: str) -> tuple[bool, str]:
    # size "s" AND trademark=yes -> delete
    if size == "s" and tm == "yes":
        return True, "rule:size=s & trademark=yes"
    # any white + jpg -> delete
    if ext == ".jpg" and color is not None and "white" in color:
        return True, "rule:white + jpg"
    # KORTE-HOFFMANN / KH-Gruppe: no *+accent variants
    if brand in {"KORTE-HOFFMANN", "KH-Gruppe"} and color in {"white+accent", "black+accent"}:
        return True, f"rule:{brand} & {color} not allowed"
    return False, ""

# ------------------------- Dest path builder -------------------------

def dest_path_for(brand_root: str, size: str | None, color: str | None, tm: str | None, is_fav: bool) -> str:
    if is_fav:
        return os.path.join(brand_root, "Favicons")
    sz = size if size in SIZE_CANON else "l"
    cl = color if color in COLOR_CANON else "black"
    tr = tm if tm in TRADEMARK_CANON else "no"
    color_dir = {
        "white": "Color=White",
        "black": "Color=Black",
        "white+accent": "Color=White+Accent",
        "black+accent": "Color=Black+Accent",
    }[cl]
    return os.path.join(
        brand_root,
        f"Size={sz.upper()}",
        color_dir,
        f"Trademark={'Yes' if tr=='yes' else 'No'}",
    )

# ------------------------- ZIP helpers -------------------------

def collect_variant_groups(root: str):
    groups = defaultdict(list)
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext in ALLOWED_EXTS:
                base, _ = os.path.splitext(fn)
                groups[os.path.join(dirpath, base)].append(os.path.join(dirpath, fn))
    for base, files in groups.items():
        zip_path = base + ".zip"
        yield zip_path, sorted(files)

def make_zip(zip_path: str, files: list[str], overwrite: bool):
    if os.path.exists(zip_path):
        if not overwrite:
            return "skip_exists"
        try:
            os.remove(zip_path)
        except Exception:
            pass
    os.makedirs(os.path.dirname(zip_path), exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            if os.path.isfile(f):
                zf.write(f, arcname=os.path.basename(f))
    return "created"

def zip_per_brand(brand_root: str, overwrite: bool):
    parent = os.path.dirname(brand_root)
    brand_name = os.path.basename(brand_root.rstrip(os.sep))
    zip_path = os.path.join(parent, f"{brand_name}.zip")
    if os.path.exists(zip_path) and not overwrite:
        return "skip_exists"
    if os.path.exists(zip_path):
        try: os.remove(zip_path)
        except Exception: pass
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for dirpath, _, filenames in os.walk(brand_root):
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, start=parent)
                zf.write(full, arcname=rel)
    return "created"

# ------------------------- Sorting core -------------------------

def sort_from_dot_sort(base_dir: str, overwrite: bool, progress_step: int, debug: bool):
    dot_sort = os.path.join(base_dir, ".sort")
    if not os.path.isdir(dot_sort):
        err(f"{os.path.relpath(dot_sort, base_dir)} not found.")
        return {
            "kept":0, "moved":0, "deleted":0, "skipped":0, "renamed":0
        }

    files = []
    for fn in os.listdir(dot_sort):
        full = os.path.join(dot_sort, fn)
        if not os.path.isfile(full):
            continue
        # Skip hidden/metadata files
        if fn.startswith("."):
            continue
        if fn.lower() in SKIP_FILES:
            continue
        files.append(full)

    total = len(files)
    info(f"Sorting from .sort | files: {total}")

    stats = {"kept":0, "moved":0, "deleted":0, "skipped":0, "renamed":0}
    for i, full in enumerate(files, 1):
        d, fn = os.path.dirname(full), os.path.basename(full)
        stem, ext = os.path.splitext(fn)
        ext_l = ext.lower()

        # process only allowed types
        if ext_l not in ALLOWED_EXTS:
            stats["skipped"] += 1
            if debug: dbg(f"skip(ext): {fn}")
            continue

        # normalize only the stem, keep/lower ext
        new_stem = normalize_stem(stem)
        new_fn = f"{new_stem}{ext_l}"
        if new_fn != fn:
            new_full = os.path.join(d, new_fn)
            try:
                if os.path.exists(new_full):
                    try: os.remove(new_full)
                    except Exception: pass
                os.rename(full, new_full)
                full = new_full
                fn = new_fn
                stem = new_stem
                stats["renamed"] += 1
                if debug: dbg(f"renamed: {fn}")
            except FileNotFoundError:
                # File vanished between list & rename (rare on Windows) – skip safely
                warn(f"rename race, skipping: {fn}")
                stats["skipped"] += 1
                continue

        # brand
        brand = detect_brand_from_name(stem)
        if brand is None:
            stats["skipped"] += 1
            if debug: dbg(f"skip(no brand): {fn}")
            continue

        size, tm, color = parse_tokens(stem)
        del_flag, reason = should_delete(brand, size, tm, color, ext_l, stem)
        if del_flag:
            try:
                os.remove(full)
                stats["deleted"] += 1
                if debug: dbg(f"delete({reason}): {fn}")
            except Exception as e:
                warn(f"failed delete {fn}: {e}")
            continue

        brand_root = ensure_brand_root(base_dir, brand)
        subdir = dest_path_for(brand_root, size, color, tm, is_favicon(stem))
        os.makedirs(subdir, exist_ok=True)

        dest = os.path.join(subdir, fn)
        if os.path.exists(dest) and overwrite:
            try: os.remove(dest)
            except Exception: pass
        if not os.path.exists(dest):
            try:
                shutil.move(full, dest)
                stats["moved"] += 1
                if debug: dbg(f"move -> {os.path.relpath(dest, base_dir)}")
            except Exception as e:
                warn(f"failed move {fn} -> {dest}: {e}")
                stats["skipped"] += 1
        else:
            stats["skipped"] += 1
            if debug: dbg(f"skip(exists): {os.path.relpath(dest, base_dir)}")

        if progress_step and (i % progress_step == 0 or i == total):
            info(f"Progress: {i}/{total}")

    info("Post-sort ZIP crawl start")
    crawl_stats = crawl_and_zip(base_dir, overwrite=overwrite, progress_step=progress_step, debug=debug, do_repairs=False)
    info("Post-sort ZIP crawl done")

    return stats | {f"zip_{k}": v for k, v in crawl_stats.items()}

# ------------------------- Crawl/Repair & ZIP -------------------------

def crawl_and_zip(base_dir: str, overwrite: bool, progress_step: int, debug: bool, do_repairs: bool=True):
    stats = {
        "kept":0, "deleted":0,
        "zip_variant_created":0, "zip_variant_skip_exists":0,
        "zip_brand_created":0, "zip_brand_skip_exists":0
    }

    brand_roots = []
    listing = [d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]
    for b in BRAND_CANON:
        if any(d.lower() == b.lower() for d in listing):
            real = next(d for d in listing if d.lower() == b.lower())
            brand_roots.append(os.path.join(base_dir, real))

    info("Crawl/Repair & ZIP start")
    for br in brand_roots:
        count_files = 0
        for dirpath, _, filenames in os.walk(br):
            count_files += len(filenames)
        info(f"[{os.path.basename(br)}] Dateien: {count_files}")

        processed = 0
        for dirpath, _, filenames in os.walk(br):
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                stem, ext = os.path.splitext(fn)
                ext_l = ext.lower()

                # Skip non-target files during repairs, but still count for progress
                if ext_l not in ALLOWED_EXTS:
                    processed += 1
                    if progress_step and (processed % progress_step == 0 or processed == count_files):
                        info(f"[{os.path.basename(br)}] Progress: {processed}/{count_files}")
                    continue

                brand = detect_brand_from_name(stem) or os.path.basename(br)
                size, tm, color = parse_tokens(stem)

                if do_repairs:
                    del_flag, reason = should_delete(brand, size, tm, color, ext_l, stem)
                    if del_flag:
                        try:
                            os.remove(full)
                            stats["deleted"] += 1
                            if debug: dbg(f"repair delete({reason}): {os.path.relpath(full, base_dir)}")
                        except Exception as e:
                            warn(f"failed delete during crawl: {full}: {e}")
                    else:
                        stats["kept"] += 1
                else:
                    stats["kept"] += 1

                processed += 1
                if progress_step and (processed % progress_step == 0 or processed == count_files):
                    info(f"[{os.path.basename(br)}] Progress: {processed}/{count_files}")

        # Variant ZIPs
        for zip_path, files in collect_variant_groups(br):
            status = make_zip(zip_path, files, overwrite=overwrite)
            if status == "created":
                stats["zip_variant_created"] += 1
                if debug: dbg(f"zip variant + {os.path.relpath(zip_path, base_dir)}")
            else:
                stats["zip_variant_skip_exists"] += 1

        # Brand ZIP
        brand_zip_status = zip_per_brand(br, overwrite=overwrite)
        if brand_zip_status == "created":
            stats["zip_brand_created"] += 1
            if debug: dbg(f"zip brand + {os.path.basename(br)}.zip")
        else:
            stats["zip_brand_skip_exists"] += 1

    info("Crawl/Repair & ZIP done")
    return stats

# ------------------------- CLI / Menu -------------------------

def main():
    parser = argparse.ArgumentParser(description="Sort & ZIP KH logos")
    parser.add_argument("--mode", choices=["sort","crawl"], default=None, help="sort = sort from .sort then crawl/zip; crawl = crawl/repair & zip only")
    parser.add_argument("--overwrite", action="store_true", default=True, help="overwrite files/ZIPs (default: True)")
    parser.add_argument("--no-overwrite", action="store_false", dest="overwrite", help="do not overwrite")
    parser.add_argument("--progress", type=int, default=1000, help="progress step (files). 0 to disable")
    parser.add_argument("--debug", action="store_true", default=False, help="verbose debug output")
    parser.add_argument("--dry-run", action="store_true", default=False, help="analyze only (no writes) [kept for compatibility]")
    parser.add_argument("--menu", action="store_true", default=False, help="force interactive menu")
    args = parser.parse_args()

    base_dir = os.getcwd()
    mode = args.mode

    if args.menu or mode is None:
        print()
        print("Select mode:")
        print("  [1] Sort .sort (then ZIP by crawling)")
        print("  [2] Crawl/Repair & ZIP only")
        choice = input("Enter 1 or 2: ").strip()
        if choice == "1": mode = "sort"
        elif choice == "2": mode = "crawl"
        else:
            err("Invalid selection. Exiting.")
            sys.exit(1)

    info(f"root={base_dir}  mode={mode}  debug={args.debug}  dry_run=False  overwrite={args.overwrite}  progress={args.progress}")

    if mode == "sort":
        stats = sort_from_dot_sort(base_dir, overwrite=args.overwrite, progress_step=args.progress, debug=args.debug)
    else:
        stats = crawl_and_zip(base_dir, overwrite=args.overwrite, progress_step=args.progress, debug=args.debug, do_repairs=True)

    print("\n[SUMMARY]")
    for k in sorted(stats.keys()):
        print(f"  {k:24s}: {stats[k]}")
    print()

if __name__ == "__main__":
    main()
