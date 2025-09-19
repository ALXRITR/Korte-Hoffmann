"""
sort-logos.py

Two modes:
  --mode sort  : process files inside ./".sort"
  --mode audit : crawl existing brand folders, fix structure/names, apply deletes, and (re)generate zips if missing

Rules covered:
- Normalize filenames: lowercase, umlauts->ascii (ä→ae, ö→oe, ü→ue, ß→ss), spaces->"-"
  BUT around '+': compress spaces so "architekten + ingenieure" -> "architekten+ingenieure" (no '-' around '+')
- Brands (top-level): architekten+ingenieure, gruppe, gebaeudedruck, immobilien (+ korte-hoffmann for KH favicons/monogram)
- "dreihaus" belongs to brand "gebaeudedruck"
- Subtree (created if brand folder exists/needed):
    Brand/
      Favicons/
      Size=L/
      Size=M/
      Size=S/
        each has Color=White / Color=Black / Color=Black+Accent / Color=White+Accent/
          each has Trademark=Yes / Trademark=No/
- Place files by parsed attributes (size/color/trademark). Favicons & monogram go under Brand/Favicons.
- Delete rules:
    1) any WHITE JPG -> delete
    2) size == s AND trademark == yes (not "no-trademark") -> delete
    3) if brand in {korte-hoffmann variants, group/gruppe} AND color in {white+accent, black+accent} -> delete
- Zips:
    A) Per brand: zip the whole Brand folder (placed at Brand/<brand>.zip)
    B) Per variant (same basename across formats): create <basename>.zip containing jpg/png/svg/pdf that exist.
       Place the variant zip next to the files (inside their final folder). Skip if already exists.
"""

from __future__ import annotations
import argparse
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path
from collections import defaultdict

# ---------- Config ----------
ROOT = Path(".").resolve()
SORT_DIR = ROOT / ".sort"

# Known brands (normalized tokens you expect in filenames)
KNOWN_BRANDS = (
    "architekten+ingenieure",
    "gruppe",
    "gebaeudedruck",
    "immobilien",
    "korte-hoffmann",  # parent brand (favicons/monogram special cases)
)

# Variants for KH detection (accent ban + favicon home)
KH_ALIASES = (
    "korte-hoffmann", "korte-hoffman", "kortehoffmann", "kortehoffman",
)

# Accent-ban brands
BRANDS_ACCENT_BAN = KH_ALIASES + ("group", "gruppe")

# Extensions we care about
VALID_EXTS = {".jpg", ".png", ".svg", ".pdf"}

# Colors we track
COLOR_MAP = {
    "white": "Color=White",
    "black": "Color=Black",
    "white+accent": "Color=White+Accent",
    "black+accent": "Color=Black+Accent",
}

# Trademark mapping
TRADEMARK_MAP = {
    "trademark": "Trademark=Yes",
    "no-trademark": "Trademark=No",
    "yes": "Trademark=Yes",
    "no": "Trademark=No",
}

# Sizes mapping (letters -> folder names)
SIZE_MAP = {"l": "Size=L", "m": "Size=M", "s": "Size=S"}

# Patterns
# Typical basename structure contains these tokens in any order: brand, left/center/right, compact/not-compact,
# bar/no-bar, size(l/m/s), no-trademark|trademark, color(white/black/white+accent/black+accent)
RE_SIZE = re.compile(r"(?:^|_)([lms])(?:_|$)")
RE_TRADE = re.compile(r"(?:^|_)((?:no-)?trademark|yes|no)(?:_|$)")
RE_COLOR = re.compile(r"(?:^|_)(white\+accent|black\+accent|white|black)(?:_|$)")

# Special favicon/monogram detection
RE_FAVICON = re.compile(r"(?:^|_)favicon(?:_|$)")
RE_MONOGRAM = re.compile(r"(?:^|_)monogram(?:_|$)")

# Dreihaus -> Gebaeudedruck mapping trigger
RE_DREIHAUS = re.compile(r"dreihaus")

# brand tokens (some raw -> normalized)
BRAND_ALIASES = {
    "architekten+ingenieure": "architekten+ingenieure",
    "architekten-ingenieure": "architekten+ingenieure",
    "architekten ingenieure": "architekten+ingenieure",
    "gruppe": "gruppe",
    "group": "gruppe",
    "gebaeudedruck": "gebaeudedruck",
    "immobilien": "immobilien",
    "korte-hoffmann": "korte-hoffmann",
    "korte-hoffman": "korte-hoffmann",
    "kortehoffmann": "korte-hoffmann",
    "kortehoffman": "korte-hoffmann",
}

# ---------- Helpers ----------

def normalize_umlauts(s: str) -> str:
    repl = (
        ("ä", "ae"), ("ö", "oe"), ("ü", "ue"),
        ("Ä", "ae"), ("Ö", "oe"), ("Ü", "ue"),
        ("ß", "ss"),
    )
    for a, b in repl:
        s = s.replace(a, b)
    return s

def normalize_filename(raw: str) -> str:
    """
    Lowercase, remove umlauts, replace spaces with '-', but
    compress spaces around '+' so 'a + b' -> 'a+b'.
    Keep existing hyphens/underscores/plus.
    """
    name, ext = os.path.splitext(raw)
    # umlauts
    name = normalize_umlauts(name)
    # trim/normalize spaces around '+'
    # first compress "space + space" to '+'
    name = re.sub(r"\s*\+\s*", "+", name)
    # remaining spaces -> '-'
    name = re.sub(r"\s+", "-", name)
    # lowercase
    name = name.lower()
    # disallow double hyphens (cosmetic)
    name = re.sub(r"-{2,}", "-", name).strip("-_")
    # final
    return f"{name}{ext.lower()}"

def detect_brand_from_name(name_l: str) -> str | None:
    # Dreihaus implies Gebaeudedruck
    if RE_DREIHAUS.search(name_l):
        return "gebaeudedruck"
    # direct tokens
    for raw, norm in BRAND_ALIASES.items():
        if raw in name_l:
            return norm
    # otherwise try to guess from leading token
    head = name_l.split("_", 1)[0]
    return BRAND_ALIASES.get(head, None)

def parse_attrs(name_l: str) -> tuple[str|None, str|None, str|None]:
    """Return (size, color, trademark) as normalized tokens (l/m/s, white/black/white+accent/black+accent, yes/no)."""
    size = None
    m = RE_SIZE.search(name_l)
    if m:
        size = m.group(1)

    color = None
    m = RE_COLOR.search(name_l)
    if m:
        color = m.group(1)

    tm = None
    m = RE_TRADE.search(name_l)
    if m:
        token = m.group(1)
        if token in ("yes", "trademark"):
            tm = "yes"
        elif token in ("no", "no-trademark"):
            tm = "no"
        else:
            tm = token
    return size, color, tm

def is_banned_accent_combo(name_l: str) -> bool:
    if ("white+accent" in name_l) or ("black+accent" in name_l):
        return any(b in name_l for b in BRANDS_ACCENT_BAN)
    return False

def should_delete(name_l: str, suffix: str) -> bool:
    # A) KH/group accent ban
    if is_banned_accent_combo(name_l):
        return True
    # B) any WHITE JPG
    if "white" in name_l and suffix == ".jpg":
        return True
    # C) size S + trademark YES
    size, color, trademark = parse_attrs(name_l)
    if (size == "s") and (trademark == "yes"):
        return True
    return False

def ensure_brand_structure(brand_dir: Path) -> None:
    """Create the full folder tree for a brand."""
    # Favicons
    (brand_dir / "Favicons").mkdir(parents=True, exist_ok=True)
    # Sizes/Colors/Trademarks
    for size_dir in SIZE_MAP.values():
        for color_dir in COLOR_MAP.values():
            for tm_dir in TRADEMARK_MAP.values():
                (brand_dir / size_dir / color_dir / tm_dir).mkdir(parents=True, exist_ok=True)

def place_target_for_file(brand: str, name_l: str) -> Path | None:
    """Compute the destination directory (not including filename)."""
    brand_dir = ROOT / brand
    ensure_brand_structure(brand_dir)

    # Favicons / Monogram go to Favicons
    if RE_FAVICON.search(name_l) or RE_MONOGRAM.search(name_l):
        return brand_dir / "Favicons"

    size, color, trademark = parse_attrs(name_l)

    # If not parsed, we cannot place
    if size not in SIZE_MAP or color not in COLOR_MAP or trademark not in ("yes", "no"):
        return None

    size_folder = SIZE_MAP[size]
    color_folder = COLOR_MAP[color]
    tm_folder = TRADEMARK_MAP["trademark" if trademark == "yes" else "no-trademark"]
    return brand_dir / size_folder / color_folder / tm_folder

def move_file(src: Path, dst_dir: Path, new_name: str) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / new_name
    # if moving within same directory with only rename, use replace
    if src.resolve() == dst.resolve():
        return dst
    # if exists and is same content? We'll overwrite safely by replacing
    return shutil.move(str(src), str(dst))

def make_zip(zip_path: Path, files: list[Path]) -> None:
    if not files:
        return
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            if f.exists() and f.is_file():
                # store relative path within zip as basename only
                zf.write(f, arcname=f.name)

def zip_brand_folder(brand_dir: Path) -> None:
    zip_path = brand_dir / (brand_dir.name + ".zip")
    # rebuild each time to ensure freshness
    files = [p for p in brand_dir.rglob("*") if p.is_file() and p.suffix.lower() in VALID_EXTS]
    make_zip(zip_path, files)

def build_variant_zips_in_dir(directory: Path) -> None:
    """
    For all files in 'directory', create zip per variant (basename without extension). Include jpg/png/svg/pdf that exist.
    Place <basename>.zip in 'directory'. Skip if already exists with same members count; otherwise (re)build.
    """
    by_base = defaultdict(list)
    for f in directory.iterdir():
        if f.is_file() and f.suffix.lower() in VALID_EXTS:
            by_base[f.stem].append(f)

    for base, files in by_base.items():
        zip_path = directory / f"{base}.zip"
        # make/refresh zip
        make_zip(zip_path, sorted(files))

def audit_and_fix_brand_tree(brand_root: Path) -> None:
    """Walk brand_root and ensure variant zips exist; also normalize any stray filenames and re-place them if needed."""
    for path in brand_root.rglob("*"):
        if path.is_file():
            # Normalize filename
            norm = normalize_filename(path.name)
            norm_path = path.with_name(norm)
            if norm_path != path:
                if norm_path.exists():
                    path.unlink(missing_ok=True)
                    path = norm_path
                else:
                    path = Path(shutil.move(str(path), str(norm_path)))

    # Rebuild variant zips inside all leaf directories (incl. Favicons)
    for d in [p for p in brand_root.rglob("*") if p.is_dir()]:
        build_variant_zips_in_dir(d)

# ---------- Core processing ----------

def handle_one_file(src: Path) -> None:
    if not src.is_file():
        return
    if src.suffix.lower() not in VALID_EXTS:
        return

    norm_name = normalize_filename(src.name)
    name_l = os.path.splitext(norm_name)[0]  # lowercased within normalize

    # Brand detection
    brand = detect_brand_from_name(name_l)

    # Dreihaus -> Gebaeudedruck already handled in detect_brand
    # If favicon+monogram without explicit brand, default to KH
    if (brand is None) and (RE_FAVICON.search(name_l) or RE_MONOGRAM.search(name_l)):
        brand = "korte-hoffmann"

    if brand is None or brand not in KNOWN_BRANDS:
        # unknown – skip silently
        return

    # deletion rules
    if should_delete(name_l, src.suffix.lower()):
        src.unlink(missing_ok=True)
        return

    # destination
    dst_dir = place_target_for_file(brand, name_l)
    if dst_dir is None:
        # can't place (missing attrs) => keep under brand root as fallback
        dst_dir = ROOT / brand

    # move (and rename if needed)
    new_path = move_file(src, dst_dir, norm_name)

def process_sort_mode() -> None:
    if not SORT_DIR.exists():
        print("[FEHLER] .sort nicht gefunden.", file=sys.stderr)
        return
    for p in sorted(SORT_DIR.iterdir()):
        handle_one_file(p)

    # After moving, create brand zips and variant zips
    for brand in KNOWN_BRANDS:
        brand_dir = ROOT / brand
        if brand_dir.exists():
            ensure_brand_structure(brand_dir)
            # Create variant zips recursively
            for d in [brand_dir] + [p for p in brand_dir.rglob("*") if p.is_dir()]:
                build_variant_zips_in_dir(d)
            # Brand zip
            zip_brand_folder(brand_dir)

def process_audit_mode() -> None:
    # Crawl existing brand folders, fix names/placements where possible, rebuild zips.
    # Also sweep stray files at root (non-.sort) that belong to a brand.
    # 1) Pass over root files
    for p in ROOT.iterdir():
        if p.is_file() and p.suffix.lower() in VALID_EXTS:
            handle_one_file(p)

    # 2) Audit each brand tree
    for brand in KNOWN_BRANDS:
        bdir = ROOT / brand
        if bdir.exists():
            audit_and_fix_brand_tree(bdir)
            # ensure full structure
            ensure_brand_structure(bdir)
            # brand zip
            zip_brand_folder(bdir)

    # 3) Also check any misfiled files under arbitrary folders: try to re-handle them
    for p in ROOT.rglob("*"):
        # skip .sort and zips
        if SORT_DIR in p.parents:
            continue
        if p.suffix.lower() == ".zip":
            continue
        if p.is_file() and p.suffix.lower() in VALID_EXTS:
            # attempt delete/move based on its (possibly wrong) name
            handle_one_file(p)

    # final pass: rebuild variant zips again (to include freshly moved files)
    for brand in KNOWN_BRANDS:
        bdir = ROOT / brand
        if bdir.exists():
            for d in [bdir] + [p for p in bdir.rglob("*") if p.is_dir()]:
                build_variant_zips_in_dir(d)
            zip_brand_folder(bdir)

# ---------- CLI ----------

def main():
    ap = argparse.ArgumentParser(description="Sort/crawl KOHO logo exports.")
    ap.add_argument("--mode", choices=["sort", "audit"], default="sort",
                    help="sort: process ./.sort ; audit: crawl & fix existing folders")
    args = ap.parse_args()

    if args.mode == "sort":
        process_sort_mode()
    else:
        process_audit_mode()

if __name__ == "__main__":
    main()
