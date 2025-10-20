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

BRAND_CANON = [
    "KH-Architekten+Ingenieure",
    "KH-Gebaeudedruck",
    "KH-Gruppe",
    "KH-Immobilien",
    "KORTE-HOFFMANN",
]

ASSET_TYPE_KEYS = {
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
    # New Size Variants
    "size-xxs": {"group": "optical_size", "value": "xxs", "name": "Extra Extra Small"},
    "size-m":   {"group": "optical_size", "value": "m", "name": "Medium"},
    "size-xxl": {"group": "optical_size", "value": "xxl", "name": "Extra Extra Large"},

    # Legacy Size Variants (for old dreihaus files, mapping to new values)
    "size-s": {"group": "optical_size", "value": "xxs", "name": "Small (Legacy)"},
    "size-l": {"group": "optical_size", "value": "xxl", "name": "Large (Legacy)"},
    
    "black": {"group": "color", "name": "Black"}, "white": {"group": "color", "name": "White"},
    "black+accent": {"group": "color", "name": "Black+Accent"}, "white+accent": {"group": "color", "name": "White+Accent"},
    
    "center": {"group": "lockup", "name": "Center"}, "left": {"group": "lockup", "name": "Left"},
    "right": {"group": "lockup", "name": "Right"}, "no-lockup": {"group": "lockup", "name": "No Lockup"},
    
    "bar": {"group": "bar", "value": True, "name": "Bar"}, "no-bar": {"group": "bar", "value": False, "name": "No Bar"},
    "compact": {"group": "compact", "value": True, "name": "Compact"}, "not-compact": {"group": "compact", "value": False, "name": "Not Compact"},
    "trademark": {"group": "trademark", "value": True, "name": "With ®"}, "no-trademark": {"group": "trademark", "value": False, "name": "Without ®"},
    "clearspace": {"group": "clearspace", "value": True, "name": "With Clearspace"}, "no-clearspace": {"group": "clearspace", "value": False, "name": "Without Clearspace"},

    # Modifiers are recognized but not part of the manifest
    "rgb": {"group": "modifier"},
    "cmyk": {"group": "modifier"},
}

REQUIRED_BY_ASSET_TYPE = {
    "standard_logo": {"division", "optical_size", "color", "lockup", "bar", "compact", "trademark", "clearspace"},
    "dreihaus": {"optical_size", "color", "trademark", "clearspace"},
    "monogram": {"color"},
    "favicon": {"color"},
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
    sorted_brand_keys = sorted([k for k, v in ASSET_TYPE_KEYS.items() if v['type'] == 'standard_logo' or k == 'dreihaus'], key=len, reverse=True)

    for url in urls:
        filename, _ = os.path.splitext(os.path.basename(url))
        
        # --- ROBUSTNESS: IGNORE TOP-LEVEL BRAND ZIPS ---
        if filename in BRAND_CANON:
            ignored_log.append({'file': filename, 'reason': f"Ignoring top-level brand ZIP file."})
            continue

        parts_str = filename.lower().replace('kh-', '')
        raw_variants, unmatched = {}, []
        
        # --- RE-ARCHITECTED PARSING LOGIC ---
        brand_key = None
        asset_key = None
        
        # Step 1: Identify the Brand/Base Asset at the start of the string
        for key in sorted_brand_keys:
            if parts_str.startswith(key):
                brand_key = key
                break
        
        if not brand_key:
            # Handle special cases that don't start with a brand (e.g., monogram_black.svg)
            if 'monogram' in parts_str: asset_key = 'monogram'
            elif 'favicon' in parts_str: asset_key = 'favicon'
            else:
                ignored_log.append({'file': filename, 'reason': f"Could not identify a known brand or asset type."})
                continue
        
        # Step 2: Determine final Asset Type and remaining parts
        asset_key = asset_key or brand_key # Use brand_key if no special key was found yet
        remaining_str = parts_str
        
        if brand_key:
            remaining_str = parts_str[len(brand_key):].strip('_')
            # Check if a special type overrides the default
            if 'favicon' in remaining_str: asset_key = 'favicon'
            elif 'monogram' in remaining_str: asset_key = 'monogram'

        asset_info = ASSET_TYPE_KEYS[asset_key]
        raw_variants['asset_type'] = asset_info.get('type', asset_key)
        
        if asset_info['type'] == 'standard_logo':
            raw_variants['division'] = brand_key or asset_key
        elif brand_key and brand_key != asset_key: # e.g. korte-hoffmann_monogram
            raw_variants['division'] = brand_key

        # Step 3: Parse all remaining parts into variants
        remaining_parts = remaining_str.split('_') if remaining_str else []
        for part in remaining_parts:
            if part in VARIANT_PART_DEFINITIONS:
                definition = VARIANT_PART_DEFINITIONS[part]
                group = definition['group']
                value = definition.get('value', part)
                raw_variants[group] = value
            elif part and part not in ASSET_TYPE_KEYS:
                unmatched.append(part)

        # Step 4: Validate
        asset_type = raw_variants['asset_type']
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

    all_defs = {k: v for k, v in VARIANT_PART_DEFINITIONS.items()}
    for k, v in ASSET_TYPE_KEYS.items():
        group_name = "division" if v.get('type') == 'standard_logo' else "asset_type"
        all_defs[k] = {"group": group_name, "name": v['name']}

    manifest = {}
    for group, options in sorted(discovered.items()):
        # --- FIX: Explicitly skip modifiers from the manifest ---
        if group == 'modifier':
            continue
            
        manifest[group] = {"name": group.replace('_', ' ').title(), "options": []}
        for option in sorted(list(options), key=lambda x: str(x)):
            name = str(option)
            # Find the human-readable name from our definitions
            for k, v in all_defs.items():
                if v.get('group') == group and v.get('value', k) == option:
                    name = v['name']
                    break
            manifest[group]["options"].append({"value": option, "name": name})
    return manifest

def group_and_finalize_logos(parsed_files):
    grouped_logos = defaultdict(dict)
    for file_data in parsed_files:
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
        unique_errors = defaultdict(list)
        for item in ignored_log:
            unique_errors[item['reason']].append(item['file'])
        
        for reason, files in unique_errors.items():
            example_file = files[0]
            if len(files) > 1:
                print(f"  - Reason: {reason} (e.g., '{example_file}' and {len(files)-1} others)")
            else:
                print(f"  - File: '{example_file}' -> Reason: {reason}")
    
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