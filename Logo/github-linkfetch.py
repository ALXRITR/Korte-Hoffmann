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

# --- Mappings: Raw Filename Parts to Display Names and Variant Groups ---
VARIANT_DEFINITIONS = {
    # This maps the raw string found in filenames to its properties.
    "architekten+ingenieure": {"group": "division", "name": "Architekten+Ingenieure"},
    "gebaeudedruck":          {"group": "division", "name": "Gebäudedruck"},
    "gruppe":                 {"group": "division", "name": "Gruppe"},
    "immobilien":             {"group": "division", "name": "Immobilien"},
    "korte-hoffmann":         {"group": "division", "name": "Korte-Hoffmann"},
    
    "s": {"group": "optical_size", "name": "Small"},
    "m": {"group": "optical_size", "name": "Medium"},
    "l": {"group": "optical_size", "name": "Large"},
    
    "black":        {"group": "color", "name": "Black"},
    "white":        {"group": "color", "name": "White"},
    "black+accent": {"group": "color", "name": "Black+Accent"},
    "white+accent": {"group": "color", "name": "White+Accent"},
    
    "center":    {"group": "lockup", "name": "Center"},
    "left":      {"group": "lockup", "name": "Left"},
    "right":     {"group": "lockup", "name": "Right"},
    "no-lockup": {"group": "lockup", "name": "No Lockup"},
    
    "bar":    {"group": "bar", "value": True, "name": "Bar"},
    "no-bar": {"group": "bar", "value": False, "name": "No Bar"},
    
    "compact":     {"group": "compact", "value": True, "name": "Compact"},
    "not-compact": {"group": "compact", "value": False, "name": "Not Compact"},
    
    "trademark":     {"group": "trademark", "value": True, "name": "With ®"},
    "no-trademark": {"group": "trademark", "value": False, "name": "Without ®"}
}


def get_all_file_urls(owner, repo, path=""):
    """Fetches all file URLs efficiently using the Git Trees API."""
    api_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/main?recursive=1"
    response = requests.get(api_url, headers={'Accept': 'application/vnd.github.v3+json'})
    if response.status_code != 200: return []
    tree = response.json().get('tree', [])
    # Filter out script files and dotfiles from the list
    ignore_files = ['.py', '.json', '.csv', '.DS_Store']
    urls = []
    for item in tree:
        if item['type'] == 'blob' and item['path'].startswith(path + '/'):
            if not any(item['path'].endswith(ext) for ext in ignore_files) and '.git' not in item['path']:
                 urls.append(f"https://raw.githubusercontent.com/{owner}/{repo}/main/{item['path']}")
    return urls

def build_variant_maps(urls):
    """Pass 1: Discover all options from filenames and build the manifest and alias maps."""
    discovered_options = defaultdict(set)
    for url in urls:
        filename, _ = os.path.splitext(os.path.basename(unquote(url)))
        for part in filename.split('_'):
            if part in VARIANT_DEFINITIONS:
                definition = VARIANT_DEFINITIONS[part]
                group = definition["group"]
                # For booleans, use the value (True/False); for others, use the raw string part.
                value_to_store = definition.get("value", part)
                discovered_options[group].add(value_to_store)

    variants_manifest = {}
    master_alias_map = defaultdict(dict)

    for group, options_set in sorted(discovered_options.items()):
        variants_manifest[group] = {"name": group.replace('_', ' ').title(), "options": []}
        sorted_options = sorted(list(options_set), key=lambda x: str(x))

        for i, option in enumerate(sorted_options):
            alias = f"alias_{i + 1}"
            master_alias_map[group][option] = alias
            
            # Find the original definition to get the display name
            name = ""
            for key, definition in VARIANT_DEFINITIONS.items():
                if definition["group"] == group and definition.get("value", key) == option:
                    name = definition["name"]
                    break
            
            variants_manifest[group]["options"].append({"alias": alias, "name": name})

    return variants_manifest, master_alias_map

def parse_logos_with_aliases(urls, master_alias_map):
    """Pass 2: Parse all logos and assign the generic aliases."""
    grouped_logos = defaultdict(dict)

    for url in urls:
        path = unquote(url)
        filename, file_ext = os.path.splitext(os.path.basename(path))
        
        raw_variants = {}
        for part in filename.split('_'):
            if part in VARIANT_DEFINITIONS:
                definition = VARIANT_DEFINITIONS[part]
                group = definition["group"]
                value = definition.get("value", part)
                raw_variants[group] = value
        
        # If no variants were found (e.g., a README file), skip it
        if not raw_variants:
            continue

        logo_aliases = {group: master_alias_map[group].get(value) for group, value in raw_variants.items()}
        
        # Ensure all variant groups have at least a null alias if not present
        for group in master_alias_map.keys():
            if group not in logo_aliases:
                logo_aliases[group] = None

        variant_key = tuple(sorted(logo_aliases.items()))
        
        format_key = 'all-formats' if file_ext.lower() == '.zip' else file_ext.lower().strip('.')
        if format_key:
            grouped_logos[variant_key][format_key] = url
            
    logos_list = [dict(variant_tuple, **{"links": links}) for variant_tuple, links in grouped_logos.items()]
    return sorted(logos_list, key=lambda x: [str(x.get(k, '')) for k in sorted(master_alias_map.keys())])

# --- Main Execution ---
print("Fetching file links from GitHub...")
all_urls = get_all_file_urls(OWNER, REPO, BASE_PATH)
print(f"Found {len(all_urls)} relevant asset URLs.")

if all_urls:
    print("Pass 1: Discovering all variants and generating alias maps...")
    variants_manifest, alias_map = build_variant_maps(all_urls)
    
    print("Pass 2: Parsing all logos and applying generic aliases...")
    logos_list = parse_logos_with_aliases(all_urls, alias_map)
    
    final_data = {"variants": variants_manifest, "logos": logos_list}
    print(f"Processing complete. Found {len(logos_list)} unique logo combinations.")

    with open(OUTPUT_FILENAME, 'w', encoding='utf-8') as f:
        json.dump(final_data, f, indent=2, ensure_ascii=False)

    print(f"\n--- Success! ---")
    print(f"Data file with generic aliases and ZIP links created as '{OUTPUT_FILENAME}'.")