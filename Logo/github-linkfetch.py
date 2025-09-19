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

# ==============================================================================
# SINGLE SOURCE OF TRUTH: All known filename parts and their meanings.
# ==============================================================================
VARIANT_DEFINITIONS = {
    # Raw filename part -> {group, value (for booleans), name (for manifest)}
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

# A file is only valid if it contains one option from EACH of these groups.
REQUIRED_VARIANT_GROUPS = {
    "division", "optical_size", "color", "lockup", 
    "bar", "compact", "trademark"
}


def get_all_file_urls(owner, repo, path=""):
    """Fetches all file URLs, ignoring script/config files."""
    api_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/main?recursive=1"
    response = requests.get(api_url, headers={'Accept': 'application/vnd.github.v3+json'})
    if response.status_code != 200: return []
    
    tree = response.json().get('tree', [])
    ignore_patterns = ['.py', '.json', '.csv', '.DS_Store', '.git', 'README']
    urls = []

    for item in tree:
        if item['type'] == 'blob' and item['path'].startswith(path + '/'):
            # Ignore if the path contains any of the ignore patterns
            if not any(pattern in item['path'] for pattern in ignore_patterns):
                 urls.append(f"https://raw.githubusercontent.com/{owner}/{repo}/main/{item['path']}")
    return urls


def parse_and_validate_files(urls):
    """
    Parses all filenames, validates them, and logs any failures.
    Returns a list of successfully parsed file data and a log of ignored files.
    """
    successfully_parsed_files = []
    ignored_files_log = []

    for url in urls:
        filename, _ = os.path.splitext(os.path.basename(unquote(url)))
        parts = filename.split('_')
        
        raw_variants = {}
        unmatched_parts = []
        duplicate_groups = []

        for part in parts:
            if part in VARIANT_DEFINITIONS:
                definition = VARIANT_DEFINITIONS[part]
                group = definition["group"]
                value = definition.get("value", part)
                
                if group in raw_variants:
                    duplicate_groups.append(group)
                else:
                    raw_variants[group] = value
            else:
                unmatched_parts.append(part)
        
        # --- Validation Step ---
        missing_groups = REQUIRED_VARIANT_GROUPS - set(raw_variants.keys())
        
        if missing_groups or unmatched_parts or duplicate_groups:
            reasons = []
            if missing_groups: reasons.append(f"Missing required variants: {sorted(list(missing_groups))}")
            if unmatched_parts: reasons.append(f"Found unmatched parts: {unmatched_parts}")
            if duplicate_groups: reasons.append(f"Found duplicate variants for group(s): {duplicate_groups}")
            ignored_files_log.append({'file': filename, 'reason': '; '.join(reasons)})
        else:
            successfully_parsed_files.append({"url": url, "raw_variants": raw_variants})
            
    return successfully_parsed_files, ignored_files_log


def create_manifest_and_aliases(parsed_files):
    """Builds the manifest and alias maps from successfully parsed files."""
    discovered_options = defaultdict(set)
    for file_data in parsed_files:
        for group, value in file_data["raw_variants"].items():
            discovered_options[group].add(value)

    variants_manifest = {}
    master_alias_map = defaultdict(dict)

    for group, options_set in sorted(discovered_options.items()):
        variants_manifest[group] = {"name": group.replace('_', ' ').title(), "options": []}
        sorted_options = sorted(list(options_set), key=lambda x: str(x))

        for i, option in enumerate(sorted_options):
            alias = f"alias_{i + 1}"
            master_alias_map[group][option] = alias
            
            name = ""
            for key, definition in VARIANT_DEFINITIONS.items():
                if definition["group"] == group and definition.get("value", key) == option:
                    name = definition["name"]
                    break
            
            variants_manifest[group]["options"].append({"alias": alias, "name": name})
    return variants_manifest, master_alias_map


def group_and_finalize_logos(parsed_files, master_alias_map):
    """Groups parsed files by their aliases and builds the final 'logos' list."""
    grouped_logos = defaultdict(dict)

    for file_data in parsed_files:
        logo_aliases = {group: master_alias_map[group].get(value) for group, value in file_data["raw_variants"].items()}
        variant_key = tuple(sorted(logo_aliases.items()))
        
        _, file_ext = os.path.splitext(file_data["url"])
        format_key = 'all-formats' if file_ext.lower() == '.zip' else file_ext.lower().strip('.')
        if format_key:
            grouped_logos[variant_key][format_key] = file_data["url"]
            
    logos_list = [dict(variant_tuple, **{"links": links}) for variant_tuple, links in grouped_logos.items()]
    return sorted(logos_list, key=lambda x: [str(x.get(k, '')) for k in sorted(master_alias_map.keys())])


# --- Main Execution ---
print("Fetching file links from GitHub...")
all_urls = get_all_file_urls(OWNER, REPO, BASE_PATH)
print(f"Found {len(all_urls)} potential asset URLs.")

if all_urls:
    print("\n--- Phase 1: Parsing and Validating all filenames ---")
    valid_files, ignored_log = parse_and_validate_files(all_urls)
    
    if ignored_log:
        print(f"WARNING: Ignored {len(ignored_log)} files due to parsing errors:")
        for entry in ignored_log:
            print(f"  - File: '{entry['file']}' -> Reason: {entry['reason']}")
    
    print(f"\nSuccessfully validated {len(valid_files)} files.")
    
    print("\n--- Phase 2: Generating Variant Manifest and Aliases ---")
    variants_manifest, alias_map = create_manifest_and_aliases(valid_files)
    print("Manifest and alias maps created.")
    
    print("\n--- Phase 3: Grouping files and finalizing JSON ---")
    logos_list = group_and_finalize_logos(valid_files, alias_map)
    
    final_data = {"variants": variants_manifest, "logos": logos_list}
    print(f"Processing complete. Found {len(logos_list)} unique logo combinations.")

    with open(OUTPUT_FILENAME, 'w', encoding='utf-8') as f:
        json.dump(final_data, f, indent=2, ensure_ascii=False)

    print(f"\n--- SUCCESS ---")
    print(f"Data file created as '{OUTPUT_FILENAME}'.")