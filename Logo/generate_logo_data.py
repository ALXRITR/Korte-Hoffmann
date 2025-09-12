import os, json, urllib.parse

BASE_DIR = '.'
BASE_URL = "https://raw.githubusercontent.com/ALXRITR/Korte-Hoffmann/main/Logo"

DIVISION_CODES = {
    "KH-Architekten+Ingenieure": ("KH", "A+I"),
    "KH-GRUPPE": ("KH", "GR"),
    "KH-Gebauudedruck": ("KH", "G"),
    "KH-Immobilien": ("KH", "I"),
    "KORTE-HOFFMANN": (None, "no-division"),
}

LOCKUP_MAP = {
    "Left": ("L", False),
    "Center": ("C", False),
    "Right": ("R", False),
    "Center-KH": ("C", True),
}

COLOR_MAP = {
    "Black": "B",
    "White": "W",
    "Color-Dark": "C-W",
    "Color-Light": "C-B",
}


def main():
    entries = {}
    for folder in sorted(os.listdir(BASE_DIR)):
        if not os.path.isdir(folder):
            continue
        info = DIVISION_CODES.get(folder)
        if not info:
            continue
        default_logotype, division_code = info
        for fname in sorted(os.listdir(folder)):
            ext = fname.rsplit('.', 1)[-1].lower()
            if ext not in {"svg", "png", "pdf", "jpg", "jpeg"}:
                continue
            stem = fname[: -(len(ext) + 1)]
            parts = stem.split('_')
            has_copyright = True
            if parts[-1] == "No-R":
                has_copyright = False
                parts = parts[:-1]
            if folder == "KORTE-HOFFMANN":
                base = parts[0]
                if base == "KH":
                    logotype = "KH"
                    is_compact = True
                else:
                    logotype = "KORTE HOFFMANN"
                    is_compact = False
                optical = parts[1] if len(parts) > 1 else ""
                lockup_code = "no-lockup"
                color_name = parts[2] if len(parts) > 2 else ""
            else:
                logotype = "KH"
                optical = parts[1] if len(parts) > 1 else ""
                lock_str = parts[2] if len(parts) > 2 else ""
                color_name = parts[3] if len(parts) > 3 else ""
                lockup_code, compact_from_lock = LOCKUP_MAP.get(lock_str, ("no-lockup", False))
                is_compact = compact_from_lock
            color_code = COLOR_MAP.get(color_name, "")
            key = (logotype, division_code, lockup_code, color_code, optical, has_copyright, is_compact)
            if key not in entries:
                entries[key] = {
                    "id": None,
                    "logotype": logotype,
                    "division": division_code,
                    "lockup": lockup_code,
                    "color": color_code,
                    "opticalSize": optical,
                    "hasCopyright": has_copyright,
                    "isCompact": is_compact,
                    "files": {},
                }
            url = f"{BASE_URL}/{urllib.parse.quote(folder)}/{urllib.parse.quote(fname)}"
            entries[key]["files"][ext if ext != "jpg" else "jpeg"] = url
    data = []
    for i, e in enumerate(entries.values(), 1):
        e["id"] = i
        files = e["files"]
        files["image"] = files.get("png") or files.get("jpeg") or files.get("svg") or files.get("pdf")
        data.append(e)
    # Write a JavaScript-style file with unquoted keys and single quotes
    import re
    json_str = json.dumps(data, ensure_ascii=False, indent=2)
    json_str = re.sub(r'"([A-Za-z0-9_]+)":', r'\1:', json_str)
    json_str = json_str.replace('"', "'")
    with open('logo-data.json', 'w', encoding='utf-8') as fh:
        fh.write(json_str)

if __name__ == "__main__":
    main()
