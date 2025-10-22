#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Korte-Hoffmann | Logo sorter & ZIPper (rev. KH-2025-10-22)

Änderungen:
- Lockups nur für: KH-Architekten+Ingenieure, KH-Gebaeudedruck (ohne DREIHAUS), KH-Immobilien, KH-Gruppe.
- KORTE-HOFFMANN: keine Lockups, keine Bar, aber (compact|no-compact)-Ebene.
- DREIHAUS: keine Lockups, keine Bar.
- Feste Ordnerhierarchie:
  * Mit Lockups:
      /<Division>/<lockup>/(bar|no-bar)/size-<xxs|m|xxl>/(trademark|no-trademark)/(clearspace|no-clearspace>/
  * KORTE-HOFFMANN:
      /KORTE-HOFFMANN/(compact|no-compact)/size-<xxs|m|xxl>/(trademark|no-trademark)/(clearspace|no-clearspace)/
  * DREIHAUS:
      /KH-Gebaeudedruck/DREIHAUS/size-<xxs|m|xxl>/(trademark|no-trademark)/(clearspace|no-clearspace)/
- Dateinamen werden auf neues Schema umgebaut, ohne "no-*"-Tokens:
  * Mit Lockups:
      <slug>_<lockup>_[bar]_ <color>_size-<xxs|m|xxl>_[trademark]_[clearspace]_(rgb|cmyk).<ext>
  * KORTE-HOFFMANN:
      <slug>_[compact]_ <color>_size-<xxs|m|xxl>_[trademark]_[clearspace]_(rgb|cmyk).<ext>
  * DREIHAUS:
      <slug>_ <color>_size-<xxs|m|xxl>_[trademark]_[clearspace]_(rgb|cmyk).<ext>
- "compact/no-compact" in Nicht-KH-Dateien werden (falls vorhanden) nur als Mapping für Lockups interpretiert:
  compact→center-compact, no-compact→center.
- Color bleibt kein Ordner. RGB/CMYK bleiben gemischt in (clearspace|no-clearspace).
- ZIPs: pro Variantengruppe (gleicher Pfad, gleicher Basisname bis auf _rgb/_cmyk) und pro Brand.

Hinweis:
- Es werden nur .jpg .png .svg .pdf verarbeitet.
- Umlaute -> ae/oe/ue/ss, Leerzeichen -> '-', lowercase, '+' bleibt.
"""

import argparse
import os
import re
import sys
import shutil
import zipfile
from collections import defaultdict
from datetime import datetime

# ------------------------- Logging -------------------------

def ts():
    return datetime.now().strftime("%H:%M:%S")

def log(level, msg):
    print(f"[{ts()}][{level}] {msg}", flush=True)

def info(msg): log("INF", msg)
def dbg(msg):  print(f"[{ts()}][DBG] {msg}", flush=True)
def warn(msg): log("WRN", msg)
def err(msg):  log("ERR", msg)

# ------------------------- Canon -------------------------

BRAND_CANON = [
    "KH-Architekten+Ingenieure",
    "KH-Gebaeudedruck",
    "KH-Gruppe",
    "KH-Immobilien",
    "KORTE-HOFFMANN",
]

DIVISIONS_WITH_LOCKUPS = {
    "KH-Architekten+Ingenieure",
    "KH-Gebaeudedruck",  # außer DREIHAUS
    "KH-Immobilien",
    "KH-Gruppe",
}

LOCKUP_CANON = ["left", "right", "center", "center-compact"]
SIZE_CANON = ["xxl", "m", "xxs"]
COLOR_CANON = ["white", "black", "white+accent", "black+accent"]

ALLOWED_EXTS = {".jpg", ".png", ".svg", ".pdf"}
SKIP_FILES = {"thumbs.db", "desktop.ini"}

# Löschen (optional, default: abfragen oder OFF via --assume-no)
DELETE_POLICY = {
    "size_xxs_tm": None,      # size=XXS & trademark=Yes
    "white_jpg": None,        # *.jpg + white/white+accent
    "accent_banned": None,    # Accent bei KH-Gruppe/KORTE-HOFFMANN
}

# ------------------------- Normalisierung -------------------------

UMLAUT_MAP = {"ä":"ae","Ä":"ae","ö":"oe","Ö":"oe","ü":"ue","Ü":"ue","ß":"ss"}

def de_umlaut(s: str) -> str:
    for k, v in UMLAUT_MAP.items():
        s = s.replace(k, v)
    return s

def normalize_stem(stem: str) -> str:
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
    if brand.lower() in existing:
        return os.path.join(base_dir, existing[brand.lower()])
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

# ------------------------- Token parsing -------------------------

def parse_tokens_full(name_no_ext: str):
    """
    Liest alle Tokens aus dem normalisierten Basisnamen.
    Gibt: slug, lockup, bar(bool), size, trademark(bool), clearspace(bool), color, mode(rgb|cmyk),
         compact(bool|None), dreihaus(bool)
    """
    n = name_no_ext
    parts = n.split("_")
    slug = parts[0] if parts else n
    tokens = set(parts[1:])

    # Basics
    lockup = None
    for lu in LOCKUP_CANON:
        if lu in tokens:
            lockup = lu
            break

    # legacy compact for non-KH lockup mapping
    legacy_compact = "compact" in tokens
    legacy_no_compact = "no-compact" in tokens

    # bars
    bar = None
    if "bar" in tokens and "no-bar" not in tokens:
        bar = True
    elif "no-bar" in tokens:
        bar = False

    # size
    size = None
    for p in parts:
        if p.startswith("size-"):
            s = p.removeprefix("size-")
            if s in SIZE_CANON:
                size = s
                break

    # trademark
    trademark = None
    if "trademark" in tokens and "no-trademark" not in tokens:
        trademark = True
    elif "no-trademark" in tokens:
        trademark = False

    # clearspace
    clearspace = None
    if "clearspace" in tokens and "no-clearspace" not in tokens:
        clearspace = True
    elif "no-clearspace" in tokens:
        clearspace = False

    # color
    color = None
    for c in COLOR_CANON:
        if c in tokens:
            color = c
            break

    # mode
    mode = "rgb" if "rgb" in tokens else ("cmyk" if "cmyk" in tokens else None)

    # KH compact flag (nur für KORTE-HOFFMANN)
    kh_compact = None
    if "compact" in tokens and "no-compact" not in tokens:
        kh_compact = True
    elif "no-compact" in tokens:
        kh_compact = False

    dreihaus = "dreihaus" in n

    return {
        "slug": slug,
        "lockup": lockup,
        "bar": bar,
        "size": size,
        "trademark": trademark,
        "clearspace": clearspace,
        "color": color,
        "mode": mode,
        "kh_compact": kh_compact,
        "legacy_compact": legacy_compact,
        "legacy_no_compact": legacy_no_compact,
        "dreihaus": dreihaus,
    }

# ------------------------- Deletions -------------------------

def should_delete(brand: str | None, size: str | None, tm: bool | None, color: str | None, ext: str, name_no_ext: str, clearspace: bool | None) -> tuple[bool, str]:
    nn = name_no_ext.lower()
    if "dreihaus" in nn:
        return False, ""

    if DELETE_POLICY.get("size_xxs_tm", False):
        if size == "xxs" and tm is True:
            return True, "rule:size=xxs & trademark=yes"

    if DELETE_POLICY.get("white_jpg", False):
        if ext == ".jpg" and color is not None and "white" in color:
            return True, "rule:white + jpg"

    if DELETE_POLICY.get("accent_banned", False):
        if brand in {"KORTE-HOFFMANN", "KH-Gruppe"} and color in {"white+accent", "black+accent"}:
            return True, f"rule:{brand} & {color} not allowed"

    return False, ""

# ------------------------- Filename builder -------------------------

def build_new_filename(brand: str, tokens: dict) -> str:
    slug = tokens["slug"]
    lockup = tokens["lockup"]
    bar = tokens["bar"]
    size = tokens["size"] or "m"
    tm = tokens["trademark"]
    cs = tokens["clearspace"]
    color = tokens["color"] or "black"
    mode = tokens["mode"] or "rgb"
    kh_compact = tokens["kh_compact"]
    dreihaus = tokens["dreihaus"]

    parts = [slug]

    if brand in DIVISIONS_WITH_LOCKUPS and not dreihaus:
        # Lockup erzwingen; Default: center
        parts.append(lockup if lockup in LOCKUP_CANON else "center")
        if bar is True:
            parts.append("bar")
    elif brand == "KORTE-HOFFMANN":
        # compact im Namen nur bei True
        if kh_compact is True:
            parts.append("compact")
    else:
        # DREIHAUS oder andere ohne Lockups: nichts
        pass

    parts.append(color)
    parts.append(f"size-{size}")
    if tm is True:
        parts.append("trademark")
    if cs is True:
        parts.append("clearspace")
    parts.append(mode)

    return "_".join(parts)

# ------------------------- Dest path builder -------------------------

def dest_path_for(brand_root: str, brand: str, tokens: dict) -> str:
    size = tokens["size"] or "m"
    tm = tokens["trademark"]
    cs = tokens["clearspace"]
    lockup = tokens["lockup"]
    bar = tokens["bar"]
    kh_compact = tokens["kh_compact"]
    dreihaus = tokens["dreihaus"]

    size_dir = f"size-{size}"
    tm_dir = "trademark" if tm is True else ("no-trademark" if tm is False else "no-trademark")
    cs_dir = "clearspace" if cs is True else ("no-clearspace" if cs is False else "no-clearspace")

    # DREIHAUS
    if brand == "KH-Gebaeudedruck" and dreihaus:
        return os.path.join(brand_root, "DREIHAUS", size_dir, tm_dir, cs_dir)

    # KORTE-HOFFMANN
    if brand == "KORTE-HOFFMANN":
        compact_dir = "compact" if kh_compact is True else "no-compact"
        return os.path.join(brand_root, compact_dir, size_dir, tm_dir, cs_dir)

    # Divisions mit Lockups
    lu = lockup if lockup in LOCKUP_CANON else "center"
    bar_dir = "bar" if bar is True else "no-bar"
    return os.path.join(brand_root, lu, bar_dir, size_dir, tm_dir, cs_dir)

# ------------------------- ZIP helpers -------------------------

def collect_variant_groups(root: str):
    groups = defaultdict(list)
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext in ALLOWED_EXTS:
                base, _ = os.path.splitext(fn)
                # _rgb/_cmyk abziehen für Gruppierung
                normalized_base = re.sub(r'_(rgb|cmyk)$', '', base)
                group_key = os.path.join(dirpath, normalized_base)
                groups[group_key].append(os.path.join(dirpath, fn))
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

# ------------------------- Safe rename -------------------------

def safe_rename_case_insensitive(src: str, dst: str) -> str:
    try:
        if os.path.normcase(src) == os.path.normcase(dst):
            tmp = src + ".__tmp__"
            os.rename(src, tmp)
            os.rename(tmp, dst)
            return dst
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
        if os.path.exists(dst):
            return dst
        raise

# ------------------------- Sort from .sort -------------------------

def sort_from_dot_sort(base_dir: str, overwrite: bool, progress_step: int, debug: bool):
    dot_sort = os.path.join(base_dir, ".sort")
    if not os.path.isdir(dot_sort):
        err(f"{os.path.relpath(dot_sort, base_dir)} not found.")
        return {"kept":0, "moved":0, "deleted":0, "skipped":0, "renamed":0}

    files = []
    for fn in os.listdir(dot_sort):
        full = os.path.join(dot_sort, fn)
        if not os.path.isfile(full):
            continue
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

        if ext_l not in ALLOWED_EXTS:
            stats["skipped"] += 1
            if debug: dbg(f"skip(ext): {fn}")
            continue

        norm_stem = normalize_stem(stem)
        # Zwischen-rename, damit weiteres Parsing stabil ist
        if norm_stem != stem or ext_l != ext:
            new_full = os.path.join(d, f"{norm_stem}{ext_l}")
            try:
                full = safe_rename_case_insensitive(full, new_full)
                stem = norm_stem
                fn = os.path.basename(full)
                stats["renamed"] += 1
                if debug: dbg(f"renamed(norm): {fn}")
            except Exception as e:
                warn(f"rename failed, keeping in .sort: {fn} ({e})")
                stats["skipped"] += 1
                continue

        tokens = parse_tokens_full(stem)
        brand = detect_brand_from_name(stem)
        if brand is None:
            stats["skipped"] += 1
            if debug: dbg(f"skip(no brand): {fn}")
            continue

        # legacy compact mapping auf Lockup für Nicht-KH
        if brand in DIVISIONS_WITH_LOCKUPS and not tokens["dreihaus"]:
            if tokens["lockup"] is None:
                if tokens["legacy_compact"]:
                    tokens["lockup"] = "center-compact"
                elif tokens["legacy_no_compact"]:
                    tokens["lockup"] = "center"

        # Defaults
        if tokens["size"] is None: tokens["size"] = "m"
        if tokens["trademark"] is None: tokens["trademark"] = False
        if tokens["clearspace"] is None: tokens["clearspace"] = False
        if tokens["bar"] is None: tokens["bar"] = False
        if tokens["kh_compact"] is None and brand == "KORTE-HOFFMANN":
            tokens["kh_compact"] = False

        del_flag, reason = should_delete(brand, tokens["size"], tokens["trademark"], tokens["color"], ext_l, stem, tokens["clearspace"])
        if del_flag:
            try:
                os.remove(full)
                stats["deleted"] += 1
                if debug: dbg(f"delete({reason}): {fn}")
            except Exception as e:
                warn(f"failed delete {fn}: {e}")
            continue

        brand_root = ensure_brand_root(base_dir, brand)
        subdir = dest_path_for(brand_root, brand, tokens)
        os.makedirs(subdir, exist_ok=True)

        # Neuer Dateiname nach Schema (ohne no-*)
        new_base = build_new_filename(brand, tokens)
        new_fn = f"{new_base}{ext_l}"
        dest = os.path.join(subdir, new_fn)

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
    crawl_stats = crawl_and_zip(base_dir, overwrite=overwrite, progress_step=progress_step, debug=debug, do_repairs=False, do_renames=False)
    info("Post-sort ZIP crawl done")
    return stats | {f"zip_{k}": v for k, v in crawl_stats.items()}

# ------------------------- Crawl/Repair & ZIP -------------------------

def crawl_and_zip(base_dir: str, overwrite: bool, progress_step: int, debug: bool, do_repairs: bool=True, do_renames: bool=False):
    stats = {
        "kept":0, "deleted":0,
        "zip_variant_created":0, "zip_variant_skip_exists":0,
        "zip_brand_created":0, "zip_brand_skip_exists":0
    }

    brand_roots = get_brand_roots(base_dir)
    info("Crawl/Repair & ZIP start")
    for br in brand_roots:
        brand_name = os.path.basename(br)
        count_files = sum(len(filenames) for _, _, filenames in os.walk(br))
        info(f"[{brand_name}] Files: {count_files}")

        processed = 0
        for dirpath, _, filenames in os.walk(br):
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                stem, ext = os.path.splitext(fn)
                ext_l = ext.lower()

                processed += 1
                if progress_step and (processed % progress_step == 0 or processed == count_files):
                    info(f"[{brand_name}] Progress: {processed}/{count_files}")

                if ext_l not in ALLOWED_EXTS:
                    continue

                tokens = parse_tokens_full(stem)
                brand = detect_brand_from_name(stem) or brand_name

                # legacy mapping
                if brand in DIVISIONS_WITH_LOCKUPS and not tokens["dreihaus"]:
                    if tokens["lockup"] is None:
                        if tokens["legacy_compact"]:
                            tokens["lockup"] = "center-compact"
                        elif tokens["legacy_no_compact"]:
                            tokens["lockup"] = "center"

                # defaults
                if tokens["size"] is None: tokens["size"] = "m"
                if tokens["trademark"] is None: tokens["trademark"] = False
                if tokens["clearspace"] is None: tokens["clearspace"] = False
                if tokens["bar"] is None: tokens["bar"] = False
                if tokens["kh_compact"] is None and brand == "KORTE-HOFFMANN":
                    tokens["kh_compact"] = False

                if do_repairs:
                    del_flag, reason = should_delete(brand, tokens["size"], tokens["trademark"], tokens["color"], ext_l, stem, tokens["clearspace"])
                    if del_flag:
                        try:
                            os.remove(full)
                            stats["deleted"] += 1
                            if debug: dbg(f"repair delete({reason}): {os.path.relpath(full, base_dir)}")
                        except Exception as e:
                            warn(f"failed delete during crawl: {full}: {e}")
                        continue

                    # Zielpfad prüfen und ggf. verschieben
                    ideal_dir = dest_path_for(br, brand, tokens)
                    current_dir = os.path.dirname(full)
                    target_path = os.path.join(ideal_dir, os.path.basename(full))

                    # Optional: umbenennen auf neues Schema
                    if do_renames:
                        new_base = build_new_filename(brand, tokens)
                        target_path = os.path.join(ideal_dir, f"{new_base}{ext_l}")

                    if os.path.normpath(current_dir) != os.path.normpath(ideal_dir) or (do_renames and os.path.basename(full) != os.path.basename(target_path)):
                        os.makedirs(ideal_dir, exist_ok=True)
                        if os.path.exists(target_path):
                            try: os.remove(target_path)
                            except Exception: pass
                        try:
                            if debug: dbg(f"Repair move/rename: {os.path.relpath(full, base_dir)} -> {os.path.relpath(target_path, base_dir)}")
                            shutil.move(full, target_path)
                        except Exception as e:
                            warn(f"Failed to repair-move {fn}: {e}")
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

def crawl_repair_and_zip(base_dir: str, progress_step: int, debug: bool):
    """
    Vollständiger Repair-Lauf: verschiebt fehlplatzierte Dateien, benennt auf neues Schema um
    und baut alle ZIPs neu.
    """
    # Erst reparieren + umbenennen
    _ = crawl_and_zip(base_dir, overwrite=True, progress_step=progress_step, debug=debug, do_repairs=True, do_renames=True)
    # Dann ZIPs sicherstellen (overwrite=True)
    stats = {"zip_variant_created":0,"zip_variant_skip_exists":0,"zip_brand_created":0,"zip_brand_skip_exists":0}
    for br in get_brand_roots(base_dir):
        for zip_path, files in collect_variant_groups(br):
            status = make_zip(zip_path, files, overwrite=True)
            if status == "created": stats["zip_variant_created"] += 1
        brand_zip_status = zip_per_brand(br, overwrite=True)
        if brand_zip_status == "created": stats["zip_brand_created"] += 1
    return stats

# ------------------------- Interaktiv -------------------------

def ask_yes_no(prompt: str, default: bool | None = None) -> bool:
    suffix = " [y/n]" if default is None else (" [Y/n]" if default else " [y/N]")
    while True:
        ans = input(f"{prompt}{suffix}: ").strip().lower()
        if ans in ("y","yes"): return True
        if ans in ("n","no"): return False
        if ans == "" and default is not None: return default
        print("Please answer y or n.")

def configure_delete_policy(non_interactive: bool):
    global DELETE_POLICY
    if non_interactive:
        for k, v in DELETE_POLICY.items():
            if v is None:
                DELETE_POLICY[k] = False
        return

    print("\nLöschregeln konfigurieren:")
    print("Hinweis: 'dreihaus' wird nie gelöscht.")
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

# ------------------------- CLI -------------------------

def main():
    parser = argparse.ArgumentParser(description="Sort & ZIP KH logos")
    parser.add_argument("--mode", choices=["sort","crawl","repair"], default=None, help="sort = from .sort; crawl = clean & zip; repair = move+rename & zip")
    parser.add_argument("--overwrite", action="store_true", default=True, help="overwrite files/ZIPs (default: True)")
    parser.add_argument("--no-overwrite", action="store_false", dest="overwrite", help="do not overwrite")
    parser.add_argument("--progress", type=int, default=1000, help="progress step (files). 0 to disable")
    parser.add_argument("--debug", action="store_true", default=False, help="verbose debug output")
    parser.add_argument("--dry-run", action="store_true", default=False, help="kept für Kompatibilität, ohne Effekt")
    parser.add_argument("--menu", action="store_true", default=False, help="force interactive menu")
    parser.add_argument("--assume-no", action="store_true", default=False, help="nicht interaktiv fragen, alle Löschregeln OFF")
    args = parser.parse_args()

    base_dir = os.getcwd()
    mode = args.mode

    if args.menu or mode is None:
        print()
        print("Select mode:")
        print("  [1] Sort from .sort (then ZIP)")
        print("  [2] Crawl, Clean & ZIP only (no moving)")
        print("  [3] Full Repair & ZIP (move+rename, clean, force ZIPs)")
        choice = input("Enter 1, 2, or 3: ").strip()
        if choice == "1": mode = "sort"
        elif choice == "2": mode = "crawl"
        elif choice == "3": mode = "repair"
        else:
            err("Invalid selection. Exiting.")
            sys.exit(1)

    configure_delete_policy(non_interactive=args.assume_no)

    info(f"root={base_dir}  mode={mode}  debug={args.debug}  overwrite={args.overwrite}  progress={args.progress}")
    info(f"delete_policy: size_xxs_tm={DELETE_POLICY['size_xxs_tm']} white_jpg={DELETE_POLICY['white_jpg']} accent_banned={DELETE_POLICY['accent_banned']}")

    if mode == "sort":
        stats = sort_from_dot_sort(base_dir, overwrite=args.overwrite, progress_step=args.progress, debug=args.debug)
    elif mode == "crawl":
        stats = crawl_and_zip(base_dir, overwrite=args.overwrite, progress_step=args.progress, debug=args.debug, do_repairs=True, do_renames=False)
    elif mode == "repair":
        z = crawl_repair_and_zip(base_dir, progress_step=args.progress, debug=args.debug)
        stats = {"zip_variant_created": z["zip_variant_created"], "zip_brand_created": z["zip_brand_created"], "zip_variant_skip_exists":0, "zip_brand_skip_exists":0}

    print("\n[SUMMARY]")
    for k in sorted(stats.keys()):
        print(f"  {k:24s}: {stats[k]}")
    print()

if __name__ == "__main__":
    main()
