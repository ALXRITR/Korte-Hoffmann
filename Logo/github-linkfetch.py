import requests
import json
import os
from urllib.parse import urlparse, unquote
from collections import defaultdict

# --- Configuration ---
OWNER = "ALXRITR"
REPO = "Korte-Hoffmann"
BASE_PATH = "Logo"
OUTPUT_FILENAME = "logo-data.json"

# --- Mappings for Display Names (This is only for the 'name' field in the manifest) ---
# It maps the raw string found in the file/folder name to a pretty display name.
DISPLAY_NAME_MAP = {
    # Divisions
    "KH-Architekten+Ingenieure": "Architekten+Ingenieure",
    "KH-GRUPPE": "Gruppe",
    "KH-Gebauudedruck": "Gebäudedruck",
    "KH-Immobilien": "Immobilien",
    "KORTE-HOFFMANN": "Korte-Hoffmann",
    # Optical Sizes
    "S": "Small", "M": "Medium", "L": "Large",
    # Colors
    "Black": "Black", "White": "White", "Color-Dark": "Black+Accent", "Color-Light": "White+Accent",
    # Lockups
    "Center": "Center", "Left": "Left", "Right": "Right", "no_lockup": "No Lockup",
    # Booleans
    True: "Yes", False: "No", # Generic, can be overridden for specific variants
}
# Custom display names for boolean variants
BAR_DISPLAY_NAMES = {True: "Bar", False: "No Bar"}
COMPACT_DISPLAY_NAMES = {True: "Compact", False: "Not Compact"}
TRADEMARK_DISPLAY_NAMES = {True: "With ®", False: "Without ®"}


def get_all_file_urls(owner, repo, path=""):
    """Fetches all file URLs efficiently using the Git Trees API."""
    api_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/main?recursive=1"
    response = requests.get(api_url, headers={'Accept': 'application/vnd.github.v3+json'})
    if response.status_code != 200: return []
    tree = response.json().get('tree', [])
    return [f"https://raw.githubusercontent.com/{owner}/{repo}/main/{item['path']}" for item in tree if item['type'] == 'blob' and item['path'].startswith(path + '/')]

def discover_and_map_aliases(urls):
    """
    First pass: Discover all options and create stable, generic alias maps for them.
    Returns the final 'variants' manifest and a master map for the parser.
    """
    discovered_raw_options = defaultdict(set)
    allowed_extensions = ['.jpg', '.jpeg', '.png', '.svg', '.pdf']

    # --- 1. Discover all raw option strings from filenames ---
    for url in urls:
        path = urlparse(unquote(url)).path
        filename = os.path.basename(path)
        file_base, file_ext = os.path.splitext(filename)
        if file_ext.lower() not in allowed_extensions: continue

        # Division
        folder_name = path.split('/')[-2]
        if folder_name in DISPLAY_NAME_MAP:
             discovered_raw_options["division"].add(folder_name)

        # Other variants from filename
        filename_parts = file_base.split('_')
        for part in filename_parts:
            if part in ["S", "M", "L"]: discovered_raw_options["optical_size"].add(part)
            if part in ["Black", "White", "Color-Dark", "Color-Light"]: discovered_raw_options["color"].add(part)
            for lockup_key in ["Center", "Left", "Right"]:
                if part.startswith(lockup_key):
                    discovered_raw_options["lockup"].add(lockup_key)
                    break
    
    # Manually add special/boolean cases
    discovered_raw_options["lockup"].add("no_lockup")
    discovered_raw_options["bar"].update([True, False])
    discovered_raw_options["compact"].update([True, False])
    discovered_raw_options["trademark"].update([True, False])

    # --- 2. Build the alias maps and the variants manifest ---
    master_alias_map = defaultdict(dict)
    variants_manifest = {
        "division": {"name": "Division", "options": []},
        "optical_size": {"name": "Optical Size", "options": []},
        "color": {"name": "Color", "options": []},
        "lockup": {"name": "Lockup", "options": []},
        "bar": {"name": "Bar", "options": []},
        "compact": {"name": "Compact", "options": []},
        "trademark": {"name": "Trademark", "options": []},
    }

    for variant_key, options_set in discovered_raw_options.items():
        # Sort options to ensure consistent alias assignment every time the script is run
        sorted_options = sorted(list(options_set), key=lambda x: str(x))
        
        for i, raw_option in enumerate(sorted_options):
            alias = f"alias_{i + 1}"
            master_alias_map[variant_key][raw_option] = alias
            
            # Determine the correct display name
            name = DISPLAY_NAME_MAP.get(raw_option)
            if variant_key == "bar": name = BAR_DISPLAY_NAMES.get(raw_option)
            if variant_key == "compact": name = COMPACT_DISPLAY_NAMES.get(raw_option)
            if variant_key == "trademark": name = TRADEMARK_DISPLAY_NAMES.get(raw_option)

            variants_manifest[variant_key]["options"].append({"alias": alias, "name": name})

    return variants_manifest, master_alias_map


def parse_logos_with_aliases(urls, master_alias_map):
    """Second pass: Parse all logos and assign the generic aliases."""
    grouped_logos = defaultdict(dict)
    allowed_extensions = ['.jpg', '.jpeg', '.png', '.svg', '.pdf']

    for url in urls:
        path = urlparse(unquote(url)).path
        filename = os.path.basename(path)
        file_base, file_ext = os.path.splitext(filename)
        if file_ext.lower() not in allowed_extensions: continue

        try:
            folder_name = path.split('/')[-2]
            if folder_name not in master_alias_map["division"]: continue

            # --- Set defaults using raw values first ---
            raw_variants = {
                "division": folder_name, "lockup": "no_lockup", "compact": False,
                "bar": False, "optical_size": None, "trademark": True, "color": None
            }

            # --- Parse filename to update raw values ---
            filename_parts = file_base.split('_')
            for part in filename_parts:
                if part in master_alias_map["optical_size"]: raw_variants["optical_size"] = part
                elif part in master_alias_map["color"]: raw_variants["color"] = part
                elif part == "No-R": raw_variants["trademark"] = False
                else:
                    for lockup_key in master_alias_map["lockup"]:
                        if part.startswith(lockup_key):
                            raw_variants["lockup"] = lockup_key
                            raw_variants["bar"] = True
                            if lockup_key == "Center" and part.endswith("-KH"):
                                raw_variants["compact"] = True
                            break
            
            # --- Convert raw values to generic aliases ---
            logo_aliases = {
                key: master_alias_map[key].get(value) for key, value in raw_variants.items()
            }
            
            variant_key = tuple(sorted(logo_aliases.items()))
            format_key = file_ext.lower().replace('.', '')
            grouped_logos[variant_key][format_key] = url

        except Exception as e:
            print(f"Could not process file: {filename} - Error: {e}")

    # Convert grouped logos to final list format
    logos_list = [dict(variant_tuple, **{"links": links}) for variant_tuple, links in grouped_logos.items()]
    return sorted(logos_list, key=lambda x: tuple(x.get(k, '') for k in variants_manifest.keys()))


# --- Main Execution ---
print("Fetching file links from GitHub...")
all_urls = get_all_file_urls(OWNER, REPO, BASE_PATH)
print(f"Found {len(all_urls)} file URLs.")

if all_urls:
    print("Pass 1: Discovering all variants and generating alias maps...")
    variants_manifest, alias_map = discover_and_map_aliases(all_urls)
    
    print("Pass 2: Parsing all logos and applying generic aliases...")
    logos_list = parse_logos_with_aliases(all_urls, alias_map)
    
    final_data = {"variants": variants_manifest, "logos": logos_list}
    print(f"Processing complete. Found {len(logos_list)} unique logo combinations.")

    with open(OUTPUT_FILENAME, 'w', encoding='utf-8') as f:
        json.dump(final_data, f, indent=2, ensure_ascii=False)

    print(f"\n--- Success! ---")
    print(f"Data file with generic aliases created as '{OUTPUT_FILENAME}'.")