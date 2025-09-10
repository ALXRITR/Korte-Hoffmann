import os
import csv
import requests

# --- KONFIGURATION ---
OWNER = "ALXRITR"
REPO = "Korte-Hoffmann"
BASE_LOCAL_PATH = "."  # Bedeutet: der Ordner, in dem das Skript läuft
BASE_REPO_PATH = "Logo"
OUTPUT_CSV_FILE = "framer-import-final.csv"

# --- MAPPING-REGELN (aus Ihrer Anleitung) ---
DIVISION_MAP = {
    "KH Architekten + Ingenieure": "A+I",
    "KH GRUPPE": "GR",
    "KH Gebäudedruck": "G",
    "KH Immobilien": "I",
    "KORTE HOFFMANN": "no-division"
}
COLOR_MAP = { "Black": "B", "White": "W", "Color (Dark)": "C-B", "Color (Light)": "C-W" }
LOCKUP_MAP = { "Left": "L", "Center": "C", "Right": "R" }

# --- FUNKTIONEN ---
def get_all_download_urls():
    """
    Ruft alle Download-URLs rekursiv von der GitHub API ab.
    Die zurückgegebenen URLs sind bereits von GitHub korrekt kodiert.
    """
    print("Rufe alle korrekten, URL-kodierten Links von der GitHub API ab...")
    all_urls = {}
    def get_contents(path=""):
        api_url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{path}"
        try:
            response = requests.get(api_url)
            response.raise_for_status()
            for item in response.json():
                if item['type'] == 'file':
                    all_urls[item['path']] = item['download_url']
                elif item['type'] == 'dir':
                    get_contents(item['path'])
        except requests.exceptions.RequestException as e:
            print(f"Fehler bei API-Abfrage für Pfad '{path}': {e}")
    get_contents(BASE_REPO_PATH)
    print(f"{len(all_urls)} Download-URLs erfolgreich abgerufen.")
    return all_urls

def parse_filename(file_path, root_folder):
    """Extrahiert alle Attribute aus dem Dateipfad und Dateinamen."""
    parts = file_path.replace(root_folder, '').strip(os.sep).split(os.sep)
    division_folder = parts[0]
    filename = parts[-1]
    data = { "Logotype": "KORTE HOFFMANN", "Division": "no-division", "LockUp": "no-lockup", "Color": "", "Optical-Size": "", "®-Symbol": "true" }
    data["Division"] = DIVISION_MAP.get(division_folder, "no-division")
    name_part = os.path.splitext(filename)[0]
    if "_No-(R)" in name_part or "_no-(R)" in name_part:
        data["®-Symbol"] = "false"
        name_part = name_part.replace("_No-(R)", "").replace("_no-(R)", "")
    if "Center (KH)" in name_part:
        data["Logotype"], data["LockUp"] = "KH", "C"
        name_part = name_part.replace("Center (KH)", "Center")
    elif name_part.startswith("KH_"): data["Logotype"], data["LockUp"] = "KH", "no-lockup"
    elif name_part.startswith("Korte-Hoffmann_"): data["Logotype"], data["LockUp"] = "KORTE HOFFMANN", "no-lockup"
    name_parts = name_part.split('_')
    if name_parts[0] in ["Architekten+Ingenieure", "Gruppe", "Gebäudedruck", "Immobilien", "Korte-Hoffmann", "KH"]: name_parts.pop(0)
    for part in name_parts:
        if part in ["S", "M", "L"]: data["Optical-Size"] = part
        elif part in LOCKUP_MAP and data["LockUp"] == "no-lockup": data["LockUp"] = LOCKUP_MAP[part]
        elif part in COLOR_MAP: data["Color"] = COLOR_MAP[part]
        elif part == "Color (Dark)": data["Color"] = "C-B"
        elif part == "Color (Light)": data["Color"] = "C-W"
    if data["Division"] == "no-division":
        data["LockUp"] = "no-lockup"
        if data["Color"] not in ["B", "W"]: data["Color"] = ""
    slug_parts = [data['Logotype'].lower().replace(' ', '-'), data['Division'].lower().replace('+', ''), data['Optical-Size'].lower(), data['LockUp'].lower(), data['Color'].lower(), "no-r" if data['®-Symbol'] == 'false' else '']
    data['Slug'] = '-'.join(filter(None, slug_parts))
    return data

# --- HAUPTSKRIPT ---
if __name__ == "__main__":
    download_urls = get_all_download_urls()
    if not download_urls: exit("Keine Download-URLs gefunden. Skript wird beendet.")
    
    grouped_items = {}
    print("Durchsuche lokale Dateien und ordne korrekte URLs zu...")
    for root, dirs, files in os.walk(BASE_LOCAL_PATH):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for filename in files:
            if not filename.lower().endswith(('.svg', '.png', '.jpg', '.jpeg', '.pdf')): continue
            
            full_path = os.path.join(root, filename)
            repo_path = f"{BASE_REPO_PATH}/{os.path.relpath(full_path, BASE_LOCAL_PATH).replace(os.sep, '/')}"
            
            if repo_path in download_urls:
                item_data = parse_filename(full_path, BASE_LOCAL_PATH)
                slug = item_data['Slug']
                if slug not in grouped_items:
                    grouped_items[slug] = item_data
                    grouped_items[slug]['files'] = {}
                
                ext = os.path.splitext(filename)[1].lower()
                correct_url = download_urls[repo_path]
                
                if ext == '.svg': grouped_items[slug]['files']['SVG'] = correct_url
                elif ext == '.png': grouped_items[slug]['files']['PNG'] = correct_url
                elif ext in ['.jpg', '.jpeg']: grouped_items[slug]['files']['JPEG'] = correct_url
                elif ext == '.pdf': grouped_items[slug]['files']['PDF'] = correct_url

    print(f"{len(grouped_items)} einzigartige Logo-Varianten gefunden.")
    
    with open(OUTPUT_CSV_FILE, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ["Slug",":draft","Logotype","Division","LockUp","Color","Optical-Size","®-Symbol","Image","Image:alt","SVG","PDF","PNG","JPEG"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        
        for slug, data in sorted(grouped_items.items()):
            svg_url = data['files'].get('SVG', '')
            alt_parts = ["KORTE HOFFMANN", data['Division'], "Logo,", f"Größe {data['Optical-Size']}," if data['Optical-Size'] else "", f"{data['LockUp'].replace('C', 'Zentriert').replace('L', 'Links').replace('R', 'Rechts')}," if data['LockUp'] != 'no-lockup' else "", f"{'KH,' if data['Logotype'] == 'KH' else ''}", f"{data['Color'].replace('B', 'Schwarz').replace('W', 'Weiß').replace('C-B', 'Farbe (Dunkel)').replace('C-W', 'Farbe (Hell)')}", "ohne ®-Symbol" if data['®-Symbol'] == 'false' else ""]
            alt_text = ' '.join(filter(None, alt_parts)).replace(" ,", ",").strip().rstrip(',')
            
            writer.writerow({
                "Slug": slug, ":draft": "false", "Logotype": data['Logotype'], "Division": data['Division'],
                "LockUp": data['LockUp'], "Color": data['Color'], "Optical-Size": data['Optical-Size'],
                "®-Symbol": data['®-Symbol'], "Image": svg_url, "Image:alt": alt_text,
                "SVG": svg_url, "PDF": data['files'].get('PDF', ''), "PNG": data['files'].get('PNG', ''),
                "JPEG": data['files'].get('JPEG', '') if data['Color'] not in ['W', 'C-W'] else ''
            })
            
    print(f"\nFertig! Die Datei '{OUTPUT_CSV_FILE}' wurde erfolgreich erstellt.")