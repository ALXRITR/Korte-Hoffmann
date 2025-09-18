from pathlib import Path
import shutil
import unicodedata
import re
import zipfile

ROOT = Path(".").resolve()
SORT_DIR = ROOT / ".sort"

DIV_MAP = {
    "architekten+ingenieure": "KH Architekten + Ingenieure",
    "gruppe":                 "KH Gruppe",
    "immobilien":             "KH Immobilien",
    "korte-hoffmann":         "KORTE HOFFMANN",
    "korte hoffmann":         "KORTE HOFFMANN",
    "gebaeudedruck":          "KH Gebäudedruck",
    "gebäudedruck":           "KH Gebäudedruck",
    "gebauededruck":          "KH Gebäudedruck",  # Tippfehler abfangen
}

BRANDS = [
    "KH Architekten + Ingenieure",
    "KH Gruppe",
    "KH Gebäudedruck",
    "KH Immobilien",
]

def normalize_filename(name: str) -> str:
    repl = {"ä":"ae","ö":"oe","ü":"ue","Ä":"Ae","Ö":"Oe","Ü":"Ue","ß":"ss"}
    for k, v in repl.items():
        name = name.replace(k, v)
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    # Leerzeichen rund um '+' entfernen (keine '-' zwischen '+')
    name = name.replace(" + ", "+").replace(" +", "+").replace("+ ", "+")
    name = name.replace(" ", "-").lower()
    name = name.replace("-+-", "+").replace("+-", "+").replace("-+", "+")
    while "--" in name:
        name = name.replace("--", "-")
    return name

def unique_path(dest: Path) -> Path:
    if not dest.exists(): return dest
    i, stem, suf = 1, dest.stem, dest.suffix
    while True:
        cand = dest.with_name(f"{stem}-{i}{suf}")
        if not cand.exists(): return cand
        i += 1

def division_for(name_l: str) -> str | None:
    if "dreihaus" in name_l:
        return "KH Gebäudedruck/Dreihaus"
    if ("monogram" in name_l) and ("korte" in name_l or "hoffmann" in name_l):
        return "KORTE HOFFMANN/Monogram"
    for key, folder in DIV_MAP.items():
        if key in name_l:
            return folder
    return None

def favicon_target(name_l: str) -> Path | None:
    if "monogram" in name_l:
        return ROOT / "KORTE HOFFMANN" / "Monogram" / "Favicons"
    div = division_for(name_l)
    if div:
        return ROOT / div / "Favicons"
    return None

def parse_attrs(name_l: str):
    m_size = re.search(r"_(l|m|s)(?:_|\.|\b)", name_l)
    size = {"l":"L", "m":"M", "s":"S"}.get(m_size.group(1), None) if m_size else None
    m_color = re.search(r"_(white\+accent|black\+accent|white|black)(?:_|\.|\b)", name_l)
    color_map = {"white":"White","black":"Black","white+accent":"White+Accent","black+accent":"Black+Accent"}
    color = color_map.get(m_color.group(1)) if m_color else None
    m_tm = re.search(r"_(no-trademark|trademark)(?:_|\.|\b)", name_l)
    tm = {"trademark":"Yes", "no-trademark":"No"}.get(m_tm.group(1)) if m_tm else None
    return size, color, tm

def nonfavicon_target(name_l: str) -> Path | None:
    div = division_for(name_l)
    if not div: return None
    size, color, tm = parse_attrs(name_l)
    parts = [ROOT / div]
    if size: parts.append(Path(f"Size={size}"))
    if color: parts.append(Path(f"Color={color}"))
    if tm:    parts.append(Path(f"Trademark={tm}"))
    return Path().joinpath(*parts)

def should_delete(name_l: str, suffix: str) -> bool:
    return "white" in name_l and suffix == ".jpg"

def zip_brand_folder(brand_dir: Path):
    if not brand_dir.exists():
        return
    # Name der ZIP ebenfalls "clean"
    zip_name = normalize_filename(brand_dir.name) + ".zip"
    zip_path = brand_dir / zip_name

    # ZIP (re)build – existierende ZIP vorher löschen, damit sie nicht ins Archiv gelangt
    if zip_path.exists():
        try: zip_path.unlink()
        except Exception: pass

    # Kompletten Brand-Ordner in eine ZIP schreiben (ohne .zip-Dateien)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in brand_dir.rglob("*"):
            if p.is_dir(): 
                continue
            if p.suffix.lower() == ".zip":
                continue
            # relativer Pfad ab Brand-Ordner, damit der Ordnername in der ZIP enthalten ist
            arcname = brand_dir.name + "/" + str(p.relative_to(brand_dir)).replace("\\", "/")
            zf.write(p, arcname=arcname)
    print(f"[ZIP]  {brand_dir.name} -> {zip_path.name}")

def main():
    if not SORT_DIR.exists():
        print(f"[INFO] '{SORT_DIR}' nicht gefunden – nichts zu tun.")
    else:
        moved = deleted = skipped = 0
        for p in SORT_DIR.iterdir():
            if not p.is_file(): continue
            name_l = p.name.lower()
            suf = p.suffix.lower()

            if should_delete(name_l, suf):
                try:
                    p.unlink(); deleted += 1
                    print(f"[DEL]  {p.name}")
                except Exception as e:
                    print(f"[SKIP] {p.name} (Löschen fehlgeschlagen: {e})"); skipped += 1
                continue

            if "favicon" in name_l:
                dest_dir = favicon_target(name_l)
                if not dest_dir:
                    print(f"[SKIP] {p.name} (Favicon, keine Division)"); skipped += 1; continue
            else:
                dest_dir = nonfavicon_target(name_l)
                if not dest_dir:
                    print(f"[SKIP] {p.name} (keine Division/Attribute)"); skipped += 1; continue

            dest_dir.mkdir(parents=True, exist_ok=True)
            new_name = normalize_filename(p.name)
            dest_path = unique_path(dest_dir / new_name)
            try:
                shutil.move(str(p), str(dest_path))
                print(f"[OK]   {p.name} -> {dest_path.relative_to(ROOT)}")
                moved += 1
            except Exception as e:
                print(f"[SKIP] {p.name} (Fehler: {e})"); skipped += 1

        print(f"\nFertig. Verschoben: {moved}, gelöscht: {deleted}, übersprungen: {skipped}")

    # --- ZIPs je Brand erstellen ---
    for brand in BRANDS:
        zip_brand_folder(ROOT / brand)

if __name__ == "__main__":
    main()
