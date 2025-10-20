#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Korte-Hoffmann | Logo sorter & ZIPper
- Three modes:
  1. sort: Sort from .sort, then ZIP.
  2. crawl: Clean existing sorted folders (delete only) & ZIP.
  3. repair: Crawl all sorted folders, move misplaced files, clean, and force-rebuild all ZIPs.
- Skips OS metadata like .DS_Store / Thumbs.db / desktop.ini
- Processes only: .jpg .png .svg .pdf
- Normalizes filenames: umlauts -> ae/oe/ue/ss, spaces -> -, lowercase
  (keeps '+' as-is for 'architekten+ingenieure')
- Special routes:
  * "korte-hoffmann_monogram_*color*" -> KORTE-HOFFMANN/Monogram/Color=*Color*
  * "*_favicon_*color*" for brands -> <Brand>/Favicons/Color=*Color*
  * Any "Dreihaus" -> KH-Gebaeudedruck/DREIHAUS/Color=*color*/Size=*size*/Trademark=*trademark*/Clearspace=*clearspace*
- Favicons/Monogram handled as above
- Folders: Size=XXL|M|XXS / Color=White|Black|White+Accent|Black+Accent / Trademark=Yes|No / Clearspace=Yes|No
- Cleaning rules (per interaktiver Bestätigung aktivierbar):
  * size XXS AND trademark=yes -> delete [RULE:size_xxs_tm]
  * any WHITE + JPG -> delete           [RULE:white_jpg]
  * brand in {KORTE-HOFFMANN, KH-Gruppe} AND color in {white+accent, black+accent} -> delete [RULE:accent_banned]
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

SIZE_CANON = ["xxl", "m", "xxs"]

TRADEMARK_CANON = ["yes", "no"]

ALLOWED_EXTS = {".jpg", ".png", ".svg", ".pdf"}

SKIP_FILES = {"thumbs.db", "desktop.ini"}

# Interaktiv konfigurierbare Löschregeln (Default: None -> wird abgefragt)
DELETE_POLICY = {
    "size_xxs_tm": None,      # size=XXS & trademark=Yes
    "white_jpg": None,        # *.jpg mit white oder white+accent
    "accent_banned": None,    # Accent bei KH-Gruppe/KORTE-HOFFMANN löschen
}

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

def get_brand_roots(base_dir: str) -> list[str]:
    brand_roots = []
    listing = [d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]
    for b in BRAND_CANON:
        if any(d.lower() == b.lower() for d in listing):
            real = next(d for d in listing if d.lower() == b.lower())
            brand_roots.append(os.path.join(base_dir, real))
    return brand_roots

# ------------------------- Variant parsing -------------------------

def parse_tokens(name_no_ext: str):
    n = name_no_ext.lower()
    size = None
    if "size-xxs" in n: size = "xxs"
    elif "size-m" in n: size = "m"
    elif "size-xxl" in n: size = "xxl"

    tm = None
    if "no-trademark" in n: tm = "no"
    elif "trademark" in n:  tm = "yes"

    color = None
    if "white+accent" in n: color = "white+accent"
    elif "black+accent" in n: color = "black+accent"
    elif "white" in n: color = "white"
    elif "black" in n: color = "black"
    
    clearspace = None
    if "no-clearspace" in n: clearspace = "no"
    elif "clearspace" in n:  clearspace = "yes"

    return size, tm, color, clearspace

def is_favicon(name_no_ext: str) -> bool:
    # favicon only
    return "favicon" in name_no_ext

def is_monogram(name_no_ext: str) -> bool:
    return "monogram" in name_no_ext

# ------------------------- Safe rename (Windows-casefix) -------------------------

def safe_rename_case_insensitive(src: str, dst: str) -> str:
    """
    Verhindert versehentliches Löschen bei Case-only-Rename auf NTFS.
    """
    try:
        # gleicher Pfad nur andere Groß-/Kleinschreibung?
        if os.path.normcase(src) == os.path.normcase(dst):
            tmp = src + ".__tmp__"
            os.rename(src, tmp)
            os.rename(tmp, dst)
            return dst
        # anderes Ziel: vorhandenes Ziel entfernen, wenn nicht dasselbe
        if os.path.exists(dst):
            try:
                same = False
                try:
                    same = os.path.samefile(src, dst)
                except Exception:
                    same = os.path.normcase(src) == os.path.normcase(dst)
                if not same:
                    os.remove(dst)
            except Exception:
                pass
        os.rename(src, dst)
        return dst
    except FileNotFoundError:
        # Falls Ziel bereits da ist, übernehme es
        if os.path.exists(dst):
            return dst
        raise

# ------------------------- Cleaning rules -------------------------

def should_delete(brand: str | None, size: str | None, tm: str | None, color: str | None, ext: str, name_no_ext: str, clearspace: str | None) -> tuple[bool, str]:
    nn = name_no_ext.lower()

    # Nie löschen: Dreihaus
    if "dreihaus" in nn:
        return False, ""

    # RULE:size_xxs_tm
    if DELETE_POLICY.get("size_xxs_tm", False):
        if size == "xxs" and tm == "yes":
            return True, "rule:size=xxs & trademark=yes"

    # RULE:white_jpg
    if DELETE_POLICY.get("white_jpg", False):
        if ext == ".jpg" and color is not None and "white" in color:
            return True, "rule:white + jpg"

    # RULE:accent_banned
    if DELETE_POLICY.get("accent_banned", False):
        if brand in {"KORTE-HOFFMANN", "KH-Gruppe"} and color in {"white+accent", "black+accent"}:
            return True, f"rule:{brand} & {color} not allowed"

    return False, ""

# ------------------------- Dest path builder -------------------------

def dest_path_for(brand_root: str, size: str | None, color: str | None, tm: str | None, is_fav: bool, is_mono: bool, is_dreihaus: bool, clearspace: str | None) -> str:
    # normalize tokens
    sz = size if size in SIZE_CANON else "m"
    cl = color if color in COLOR_CANON else "black"
    tr = tm if tm in TRADEMARK_CANON else "no"
    cs = clearspace if clearspace in ["yes", "no"] else "no"
    
    color_dir = {
        "white": "Color=White",
        "black": "Color=Black",
        "white+accent": "Color=White+Accent",
        "black+accent": "Color=Black+Accent",
    }[cl]
    
    clearspace_dir = f"Clearspace={'Yes' if cs == 'yes' else 'No'}"

    # Special: Monogram under KORTE-HOFFMANN
    if is_mono and os.path.basename(brand_root).lower() == "korte-hoffmann":
        return os.path.join(brand_root, "Monogram", color_dir)

    # Special: Favicons get Color subfolder for all brands
    if is_fav:
        return os.path.join(brand_root, "Favicons", color_dir)

    # Special: DREIHAUS path nesting under KH-Gebaeudedruck
    if is_dreihaus and os.path.basename(brand_root).lower().startswith("kh-gebaeudedruck"):
        return os.path.join(
            brand_root,
            "DREIHAUS",
            color_dir,
            f"Size={sz.upper()}",
            f"Trademark={'Yes' if tr=='yes' else 'No'}",
            clearspace_dir,
        )

    # Default
    return os.path.join(
        brand_root,
        f"Size={sz.upper()}",
        color_dir,
        f"Trademark={'Yes' if tr=='yes' else 'No'}",
        clearspace_dir,
    )

# ------------------------- ZIP helpers -------------------------

def collect_variant_groups(root: str):
    groups = defaultdict(list)
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext in ALLOWED_EXTS:
                base, _ = os.path.splitext(fn)
                # Normalize the base name by removing color mode suffixes for grouping
                normalized_base = re.sub(r'_(rgb|cmyk)$', '', base)
                # The key for grouping is the path + normalized base name
                group_key = os.path.join(dirpath, normalized_base)
                groups[group_key].append(os.path.join(dirpath, fn))

    # Yield each group to be zipped
    for group_key, files in groups.items():
        zip_path = group_key + ".zip"
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
                new_full = safe_rename_case_insensitive(full, new_full)
                full = new_full
                fn = new_fn
                stem = new_stem
                stats["renamed"] += 1
                if debug: dbg(f"renamed: {fn}")
            except Exception as e:
                warn(f"rename failed, keeping in .sort: {fn} ({e})")
                stats["skipped"] += 1
                continue

        # brand
        brand = detect_brand_from_name(stem)
        if brand is None:
            stats["skipped"] += 1
            if debug: dbg(f"skip(no brand): {fn}")
            continue

        size, tm, color, clearspace = parse_tokens(stem)
        if tm is None:
            warn(f"Trademark token missing in '{fn}', defaulting to 'no'.")
        if clearspace is None:
            warn(f"Clearspace token missing in '{fn}', defaulting to 'no'.")


        del_flag, reason = should_delete(brand, size, tm, color, ext_l, stem, clearspace)
        if del_flag:
            try:
                os.remove(full)
                stats["deleted"] += 1
                if debug: dbg(f"delete({reason}): {fn}")
            except Exception as e:
                warn(f"failed delete {fn}: {e}")
            continue

        brand_root = ensure_brand_root(base_dir, brand)
        subdir = dest_path_for(
            brand_root,
            size, color, tm,
            is_fav=is_favicon(stem),
            is_mono=is_monogram(stem),
            is_dreihaus=("dreihaus" in stem.lower()),
            clearspace=clearspace
        )
        os.makedirs(subdir, exist_ok=True)

        dest = os.path.join(subdir, fn)
        if os.path.exists(dest):
            if overwrite:
                try: os.remove(dest)
                except Exception: pass
            else:
                stats["skipped"] += 1
                if debug: dbg(f"skip(exists): {os.path.relpath(dest, base_dir)}")
                continue

        try:
            shutil.move(full, dest)
            stats["moved"] += 1
            if debug: dbg(f"move -> {os.path.relpath(dest, base_dir)}")
        except Exception as e:
            warn(f"failed move {fn} -> {dest}: {e}")
            stats["skipped"] += 1

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

    brand_roots = get_brand_roots(base_dir)

    info("Crawl/Repair & ZIP start")
    for br in brand_roots:
        count_files = sum(len(filenames) for _, _, filenames in os.walk(br))
        info(f"[{os.path.basename(br)}] Files: {count_files}")

        processed = 0
        for dirpath, _, filenames in os.walk(br):
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                stem, ext = os.path.splitext(fn)
                ext_l = ext.lower()

                processed += 1
                if progress_step and (processed % progress_step == 0 or processed == count_files):
                    info(f"[{os.path.basename(br)}] Progress: {processed}/{count_files}")

                if ext_l not in ALLOWED_EXTS:
                    continue

                brand = detect_brand_from_name(stem) or os.path.basename(br)
                size, tm, color, clearspace = parse_tokens(stem)
                if tm is None:
                    warn(f"Trademark token missing in '{fn}', defaulting to 'no'.")
                if clearspace is None:
                    warn(f"Clearspace token missing in '{fn}', defaulting to 'no'.")


                if do_repairs:
                    del_flag, reason = should_delete(brand, size, tm, color, ext_l, stem, clearspace)
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

def crawl_repair_and_zip(base_dir: str, overwrite: bool, progress_step: int, debug: bool):
    """
    NEW MODE: Crawls all brand folders, moves misplaced files, applies cleaning rules,
    and then forces a rebuild of all ZIPs.
    """
    stats = {
        "kept": 0, "deleted": 0, "repaired_moves": 0,
        "zip_variant_created": 0, "zip_variant_skip_exists": 0,
        "zip_brand_created": 0, "zip_brand_skip_exists": 0
    }

    brand_roots = get_brand_roots(base_dir)
    info("Full Repair & ZIP mode started. This will move misplaced files.")

    # --- Phase 1: Collect all files and repair locations ---
    all_files_to_check = []
    for br in brand_roots:
        for dirpath, _, filenames in os.walk(br):
            for fn in filenames:
                if os.path.splitext(fn)[1].lower() in ALLOWED_EXTS:
                    all_files_to_check.append(os.path.join(dirpath, fn))

    total = len(all_files_to_check)
    info(f"Found {total} media files to check across all brands.")

    for i, full_path in enumerate(all_files_to_check, 1):
        if not os.path.exists(full_path):
            if debug: dbg(f"Skipping already moved/deleted file: {os.path.basename(full_path)}")
            continue

        fn = os.path.basename(full_path)
        stem, ext = os.path.splitext(fn)
        ext_l = ext.lower()

        brand = detect_brand_from_name(stem)
        if not brand:
            warn(f"Could not detect brand for {fn}, skipping repair check.")
            stats["kept"] += 1
            continue

        size, tm, color, clearspace = parse_tokens(stem)
        if tm is None:
            warn(f"Trademark token missing in '{fn}', defaulting to 'no'.")
        if clearspace is None:
            warn(f"Clearspace token missing in '{fn}', defaulting to 'no'.")


        # Deletion check via policy
        del_flag, reason = should_delete(brand, size, tm, color, ext_l, stem, clearspace)
        if del_flag:
            try:
                os.remove(full_path)
                stats["deleted"] += 1
                if debug: dbg(f"repair delete({reason}): {os.path.relpath(full_path, base_dir)}")
            except Exception as e:
                warn(f"failed delete during repair: {full_path}: {e}")
            continue

        # Correct location
        brand_root = ensure_brand_root(base_dir, brand)
        ideal_dir = dest_path_for(
            brand_root,
            size, color, tm,
            is_fav=is_favicon(stem),
            is_mono=is_monogram(stem),
            is_dreihaus=("dreihaus" in stem.lower()),
            clearspace=clearspace
        )
        current_dir = os.path.dirname(full_path)

        if os.path.normpath(current_dir) != os.path.normpath(ideal_dir):
            os.makedirs(ideal_dir, exist_ok=True)
            dest_path = os.path.join(ideal_dir, fn)
            if os.path.exists(dest_path):
                try: os.remove(dest_path)
                except Exception: pass
            try:
                if debug: dbg(f"Repair move: {os.path.relpath(full_path, base_dir)} -> {os.path.relpath(dest_path, base_dir)}")
                shutil.move(full_path, dest_path)
                stats["repaired_moves"] += 1
            except Exception as e:
                warn(f"Failed to repair-move {fn}: {e}")
        else:
            stats["kept"] += 1

        if progress_step and (i % progress_step == 0 or i == total):
            info(f"Repair Progress: {i}/{total}")

    # --- Phase 2: Force rebuild all ZIPs ---
    info("Repair pass complete. Starting forced ZIP rebuild.")
    brand_roots = get_brand_roots(base_dir) # Re-fetch in case a brand folder was created
    for br in brand_roots:
        # Variant ZIPs
        for zip_path, files in collect_variant_groups(br):
            status = make_zip(zip_path, files, overwrite=True) # Force overwrite
            if status == "created": stats["zip_variant_created"] += 1
        # Brand ZIP
        brand_zip_status = zip_per_brand(br, overwrite=True) # Force overwrite
        if brand_zip_status == "created": stats["zip_brand_created"] += 1

    info("Full Repair & ZIP done.")
    return stats

# ------------------------- Interactive policy -------------------------

def ask_yes_no(prompt: str, default: bool | None = None) -> bool:
    suffix = " [y/n]" if default is None else (" [Y/n]" if default else " [y/N]")
    while True:
        ans = input(f"{prompt}{suffix}: ").strip().lower()
        if ans in ("y","yes"): return True
        if ans in ("n","no"): return False
        if ans == "" and default is not None: return default
        print("Please answer y or n.")

def configure_delete_policy(non_interactive: bool):
    """
    Fragt Nutzer pro Regel, ob gelöscht werden darf.
    Bei non_interactive=False immer fragen. Bei True werden None-Werte auf False gesetzt.
    """
    global DELETE_POLICY
    if non_interactive:
        for k, v in DELETE_POLICY.items():
            if v is None:
                DELETE_POLICY[k] = False
        return

    print("\nLöschregeln konfigurieren:")
    print("Hinweis: 'dreihaus' wird nie gelöscht, unabhängig von den Regeln.")
    if DELETE_POLICY["size_xxs_tm"] is None:
        DELETE_POLICY["size_xxs_tm"] = ask_yes_no("Regel aktivieren: size=XXS UND trademark=Yes löschen?", default=True)
    if DELETE_POLICY["white_jpg"] is None:
        DELETE_POLICY["white_jpg"] = ask_yes_no("Regel aktivieren: JPGs mit white/white+accent im Namen löschen?", default=True)
    if DELETE_POLICY["accent_banned"] is None:
        DELETE_POLICY["accent_banned"] = ask_yes_no("Regel aktivieren: Accent-Varianten bei KH-Gruppe/KORTE-HOFFMANN löschen?", default=True)

    print("\nZusammenfassung Löschregeln:")
    for k, v in DELETE_POLICY.items():
        print(f"  {k:15s}: {'ON' if v else 'OFF'}")
    proceed = ask_yes_no("Mit diesen Löschregeln fortfahren?")
    if not proceed:
        print("Abgebrochen.")
        sys.exit(0)
    print()

# ------------------------- CLI / Menu -------------------------

def main():
    parser = argparse.ArgumentParser(description="Sort & ZIP KH logos")
    parser.add_argument("--mode", choices=["sort","crawl", "repair"], default=None, help="sort = from .sort; crawl = clean & zip; repair = full check, move, clean & zip")
    parser.add_argument("--overwrite", action="store_true", default=True, help="overwrite files/ZIPs (default: True)")
    parser.add_argument("--no-overwrite", action="store_false", dest="overwrite", help="do not overwrite")
    parser.add_argument("--progress", type=int, default=1000, help="progress step (files). 0 to disable")
    parser.add_argument("--debug", action="store_true", default=False, help="verbose debug output")
    parser.add_argument("--dry-run", action="store_true", default=False, help="analyze only (no writes) [kept for compatibility]")
    parser.add_argument("--menu", action="store_true", default=False, help="force interactive menu")
    parser.add_argument("--assume-no", action="store_true", default=False, help="nicht interaktiv fragen, alle Löschregeln OFF")
    args = parser.parse_args()

    base_dir = os.getcwd()
    mode = args.mode

    # Interaktive Moduswahl
    if args.menu or mode is None:
        print()
        print("Select mode:")
        print("  [1] Sort from .sort (then ZIP)")
        print("  [2] Crawl, Clean & ZIP only (no moving)")
        print("  [3] Full Repair & ZIP (crawl, move, clean, force-rebuild ZIPs)")
        choice = input("Enter 1, 2, or 3: ").strip()
        if choice == "1": mode = "sort"
        elif choice == "2": mode = "crawl"
        elif choice == "3": mode = "repair"
        else:
            err("Invalid selection. Exiting.")
            sys.exit(1)

    # Löschregeln konfigurieren
    configure_delete_policy(non_interactive=args.assume_no)

    info(f"root={base_dir}  mode={mode}  debug={args.debug}  dry_run=False  overwrite={args.overwrite}  progress={args.progress}")
    info(f"delete_policy: size_xxs_tm={DELETE_POLICY['size_xxs_tm']} white_jpg={DELETE_POLICY['white_jpg']} accent_banned={DELETE_POLICY['accent_banned']}")

    if mode == "sort":
        stats = sort_from_dot_sort(base_dir, overwrite=args.overwrite, progress_step=args.progress, debug=args.debug)
    elif mode == "crawl":
        stats = crawl_and_zip(base_dir, overwrite=args.overwrite, progress_step=args.progress, debug=args.debug, do_repairs=True)
    elif mode == "repair":
        # In repair mode, we always want to overwrite ZIPs to ensure they are correct.
        stats = crawl_repair_and_zip(base_dir, overwrite=True, progress_step=args.progress, debug=args.debug)

    print("\n[SUMMARY]")
    for k in sorted(stats.keys()):
        print(f"  {k:24s}: {stats[k]}")
    print()

if __name__ == "__main__":
    main()