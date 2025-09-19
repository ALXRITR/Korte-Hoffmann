import requests
import json
import os
from urllib.parse import unquote
from collections import defaultdict

# --- Configuration ---
OWNER = "ALXRITR"
REPO = "Korte-Hoffmann"
BASE_PATH = "Logo"
OUTPUT_FILENAME = "logo-data.json"

# ==============================================================================
# SINGLE SOURCE OF TRUTH: All known filename parts and their meanings.
# ==============================================================================

# Define multi-part asset types first, so they are matched before single parts.
# The key is the full identifier, joined by underscores.
ASSET_TYPE_KEYS = {
    "favicon_monogram": {"name": "Favicon Monogram"},
    "architekten+ingenieure": {"name": "Architekten+Ingenieure", "type": "standard_logo"},
    "gebaeudedruck": {"name": "Gebäudedruck", "type": "standard_logo"},
    "gruppe": {"name": "Gruppe", "type": "standard_logo"},
    "immobilien": {"name": "Immobilien", "type": "standard_logo"},
    "korte-hoffmann": {"name": "Korte-Hoffmann", "type": "standard_logo"},
    "dreihaus": {"name": "Dreihaus", "type": "special_logo"},
    "favicon": {"name": "Favicon", "type": "special_logo"},
    "monogram": {"name": "Monogram", "type": "special_logo"},
}

VARIANT_PART_DEFINITIONS = {
    "s": {"group": "optical_size", "name": "Small"}, "m": {"group": "optical_size", "name": "Medium"}, "l": {"group": "optical_size", "name": "Large"},
    "black": {"group": "color", "name": "Black"}, "white": {"group": "color", "name": "White"},
    "black+accent": {"group": "color", "name": "Black+Accent"}, "white+accent": {"group": "color", "name": "White+Accent"},
    "center": {"group": "lockup", "name": "Center"}, "left": {"group": "lockup", "name": "Left"},
    "right": {"group": "lockup", "name": "Right"}, "no-lockup": {"group": "lockup", "name": "No Lockup"},
    "bar": {"group": "bar", "value": True, "name": "Bar"}, "no-bar": {"group": "bar", "value": False, "name": "No Bar"},
    "compact": {"group": "compact", "value": True, "name": "Compact"}, "not-compact": {"group": "compact", "value": False, "name": "Not Compact"},
    "trademark": {"group": "trademark", "value": True, "name": "With ®"}, "no-trademark": {"group": "trademark", "value": False, "name": "Without ®"},
    "box": {"group": "modifier", "value": "box"}
}

# Required variants for each asset type. Unlisted types have no requirements.
REQUIRED_BY_ASSET_TYPE = {
    "standard_logo": {"division", "optical_size", "color", "lockup", "bar", "compact", "trademark"},
    "dreihaus": {"optical_size", "color", "trademark"},
    "monogram": {"color"},
    "favicon": {"color"},
    "favicon_monogram": {"color"}
}

def get_all_file_urls(owner, repo, path=""):
    api_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/main?recursive=1"
    response = requests.get(api_url, headers={'Accept': 'application/vnd.github.v3+json'})
    if response.status_code != 200: return []
    tree = response.json().get('tree', [])
    ignore_patterns = ['.py', '.json', '.csv', '.DS_Store', '.git', 'README']
    urls = [f"https://raw.githubusercontent.com/{owner}/{repo}/main/{unquote(item['path'])}" for item in tree if item['type'] == 'blob' and item['path'].startswith(path + '/') and not any(p in item['path'] for p in ignore_patterns)]
    return urls

def parse_and_validate_files(urls):
    parsed_files, ignored_log = [], []
    sorted_asset_keys = sorted(ASSET_TYPE_KEYS.keys(), key=len, reverse=True)

    for url in urls:
        filename, _ = os.path.splitext(os.path.basename(url))
        parts_str = filename.lower().replace('kh-', '')
        parts = parts_str.split('_')
        
        raw_variants, unmatched = {}, []
        asset_key_found = None

        # Step 1: Find the asset type by checking for the longest matching key first
        for key in sorted_asset_keys:
            if parts_str.startswith(key):
                asset_key_found = key
                break
        
        if not asset_key_found:
            ignored_log.append({'file': filename, 'reason': f"Could not identify a known asset type at the start of the filename."})
            continue

        asset_info = ASSET_TYPE_KEYS[asset_key_found]
        raw_variants['asset_type'] = asset_info.get('type', asset_key_found)
        if raw_variants['asset_type'] == 'standard_logo':
            raw_variants['division'] = asset_key_found
        
        # Step 2: Parse remaining parts
        remaining_parts = parts_str[len(asset_key_found):].strip('_').split('_')
        if remaining_parts == ['']: remaining_parts = [] # Handle case where there are no remaining parts

        for part in remaining_parts:
            if part in VARIANT_PART_DEFINITIONS:
                definition = VARIANT_PART_DEFINITIONS[part]
                group = definition['group']
                if group != 'modifier':
                    raw_variants[group] = definition.get('value', part)
            else:
                unmatched.append(part)

        # Step 3: Validate based on asset type
        asset_type = raw_variants['asset_type']
        # Special case for division bundles
        if asset_type == 'standard_logo' and not remaining_parts:
            asset_type = 'division_bundle'
            raw_variants['asset_type'] = asset_type
        
        required = REQUIRED_BY_ASSET_TYPE.get(asset_type, set())
        missing = required - set(raw_variants.keys())

        if missing or unmatched:
            reasons = []
            if missing: reasons.append(f"Missing required variants for asset_type '{asset_type}': {sorted(list(missing))}")
            if unmatched: reasons.append(f"Found unmatched parts: {unmatched}")
            ignored_log.append({'file': filename, 'reason': '; '.join(reasons)})
        else:
            parsed_files.append({"url": url, "raw_variants": raw_variants})
            
    return parsed_files, ignored_log

def create_manifest(parsed_files):
    discovered = defaultdict(set)
    for file_data in parsed_files:
        for group, value in file_data["raw_variants"].items():
            discovered[group].add(value)
    
    # Manually add division_bundle to asset_type manifest
    discovered['asset_type'].add('division_bundle')

    all_defs = {k: v for k, v in VARIANT_PART_DEFINITIONS.items()}
    for k, v in ASSET_TYPE_KEYS.items():
        all_defs[k] = {"group": "division" if v.get('type') == 'standard_logo' else "asset_type", "name": v['name']}
    all_defs['division_bundle'] = {"group": "asset_type", "name": "Division Bundle"}

    manifest = {}
    for group, options in sorted(discovered.items()):
        manifest[group] = {"name": group.replace('_', ' ').title(), "options": []}
        for option in sorted(list(options), key=lambda x: str(x)):
            name = str(option)
            for k, v in all_defs.items():
                if v['group'] == group and v.get('value', k) == option:
                    name = v['name']
                    break
            manifest[group]["options"].append({"value": option, "name": name})
    return manifest

def group_and_finalize_logos(parsed_files):
    grouped_logos = defaultdict(dict)
    for file_data in parsed_files:
        # The key for grouping should ONLY be the variants present in the file
        variant_key = tuple(sorted(file_data["raw_variants"].items()))
        _, file_ext = os.path.splitext(file_data["url"])
        format_key = 'all-formats' if file_ext.lower() == '.zip' else file_ext.lower().strip('.')
        if format_key:
            grouped_logos[variant_key][format_key] = file_data["url"]
            
    logos_list = []
    for variant_tuple, links in grouped_logos.items():
        logo_object = dict(variant_tuple)
        logo_object["links"] = links
        logos_list.append(logo_object)
        
    return sorted(logos_list, key=lambda x: (x.get('asset_type', ''), x.get('division', '')))

# --- Main Execution ---
print("Fetching file links from GitHub...")
all_urls = get_all_file_urls(OWNER, REPO, BASE_PATH)
print(f"Found {len(all_urls)} potential asset URLs.")

if all_urls:
    print("\n--- Phase 1: Parsing and Validating all filenames ---")
    valid_files, ignored_log = parse_and_validate_files(all_urls)
    
    if ignored_log:
        print(f"\nWARNING: Ignored {len(ignored_log)} files that did not match naming convention:")
        unique_ignored = sorted(list({frozenset(d.items()) for d in ignored_log}), key=lambda x: dict(x)['file'])
        for item in unique_ignored:
            entry = dict(item)
            print(f"  - File: '{entry['file']}' -> Reason: {entry['reason']}")
    
    print(f"\nSuccessfully validated {len(valid_files)} files.")
    
    print("\n--- Phase 2: Generating Variant Manifest (Legend) ---")
    manifest = create_manifest(valid_files)
    print("Manifest created.")
    
    print("\n--- Phase 3: Grouping files and finalizing JSON ---")
    logos_list = group_and_finalize_logos(valid_files)
    
    final_data = {"variants": manifest, "logos": logos_list}
    print(f"Processing complete. Found {len(logos_list)} unique logo combinations.")

    with open(OUTPUT_FILENAME, 'w', encoding='utf-8') as f:
        json.dump(final_data, f, indent=2, ensure_ascii=False)

    print(f"\n--- SUCCESS ---")
    print(f"Data file created as '{OUTPUT_FILENAME}'.")