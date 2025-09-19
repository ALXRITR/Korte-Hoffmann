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
# Defines the primary asset types. The script will look for these first.
ASSET_TYPE_KEYS = {
    "architekten+ingenieure", "gebaeudedruck", "gruppe", "immobilien", "korte-hoffmann",
    "dreihaus", "favicon", "monogram"
}

# Defines all other variant parts.
VARIANT_PART_DEFINITIONS = {
    "s": {"group": "optical_size", "name": "Small"},
    "m": {"group": "optical_size", "name": "Medium"},
    "l": {"group": "optical_size", "name": "Large"},
    "black": {"group": "color", "name": "Black"},
    "white": {"group": "color", "name": "White"},
    "black+accent": {"group": "color", "name": "Black+Accent"},
    "white+accent": {"group": "color", "name": "White+Accent"},
    "center": {"group": "lockup", "name": "Center"},
    "left": {"group": "lockup", "name": "Left"},
    "right": {"group": "lockup", "name": "Right"},
    "no-lockup": {"group": "lockup", "name": "No Lockup"},
    "bar": {"group": "bar", "value": True, "name": "Bar"},
    "no-bar": {"group": "bar", "value": False, "name": "No Bar"},
    "compact": {"group": "compact", "value": True, "name": "Compact"},
    "not-compact": {"group": "compact", "value": False, "name": "Not Compact"},
    "trademark": {"group": "trademark", "value": True, "name": "With ®"},
    "no-trademark": {"group": "trademark", "value": False, "name": "Without ®"},
    "box": {"group": "modifier", "value": "box"} # A modifier, not a primary variant
}

# CONTEXT-AWARE VALIDATION: Required variants based on the asset type.
REQUIRED_BY_ASSET_TYPE = {
    "standard_logo": {"division", "optical_size", "color", "lockup", "bar", "compact", "trademark"},
    "dreihaus": {"optical_size", "color", "trademark"},
    "monogram": {"color"},
    "favicon": {"color"}
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
            if not any(pattern in item['path'] for pattern in ignore_patterns):
                decoded_path = unquote(item['path'])
                urls.append(f"https://raw.githubusercontent.com/{owner}/{repo}/main/{decoded_path}")
    return urls


def parse_and_validate_files(urls):
    """Parses filenames, validates them based on context, and logs failures."""
    parsed_files = []
    ignored_log = []

    for url in urls:
        filename, _ = os.path.splitext(os.path.basename(url))
        parts = filename.lower().replace('kh-', '').split('_')
        
        raw_variants = {}
        unmatched = []
        
        # Step 1: Identify Asset Type and Division from the first part
        first_part = parts[0]
        if first_part in ASSET_TYPE_KEYS:
            # Is it a standard logo division or a special asset type?
            if first_part in ["dreihaus", "favicon", "monogram"]:
                raw_variants['asset_type'] = first_part
            else:
                raw_variants['asset_type'] = 'standard_logo'
                raw_variants['division'] = first_part
        else:
            unmatched.append(first_part)

        # Step 2: Parse the rest of the parts
        for part in parts[1:]:
            if part in VARIANT_PART_DEFINITIONS:
                definition = VARIANT_PART_DEFINITIONS[part]
                group = definition['group']
                if group != 'modifier': # Modifiers are recognized but not stored as primary variants
                    raw_variants[group] = definition.get('value', part)
            else:
                unmatched.append(part)

        # Step 3: Validate based on asset type
        asset_type = raw_variants.get('asset_type')
        if not asset_type:
            ignored_log.append({'file': filename, 'reason': f"Could not determine asset type from first part: '{first_part}'"})
            continue

        required_groups = REQUIRED_BY_ASSET_TYPE.get(asset_type, set())
        missing_groups = required_groups - set(raw_variants.keys())

        if missing_groups or unmatched:
            reasons = []
            if missing_groups: reasons.append(f"Missing required variants for asset_type '{asset_type}': {sorted(list(missing_groups))}")
            if unmatched: reasons.append(f"Found unmatched parts: {unmatched}")
            ignored_log.append({'file': filename, 'reason': '; '.join(reasons)})
        else:
            parsed_files.append({"url": url, "raw_variants": raw_variants})
            
    return parsed_files, ignored_log


def create_manifest(parsed_files):
    """Builds the variant manifest from successfully parsed files."""
    discovered = defaultdict(set)
    for file_data in parsed_files:
        for group, value in file_data["raw_variants"].items():
            discovered[group].add(value)
    
    # Combine all known variant parts into one dictionary for easy name lookup
    all_definitions = {k: v for k, v in VARIANT_PART_DEFINITIONS.items()}
    for key in ASSET_TYPE_KEYS:
        all_definitions[key] = {"group": "asset_type" if key in ["dreihaus", "favicon", "monogram"] else "division", "name": key.replace('+', ' ').title()}
    all_definitions['standard_logo'] = {"group": "asset_type", "name": "Standard Logo"}


    manifest = {}
    for group, options_set in sorted(discovered.items()):
        manifest[group] = {"name": group.replace('_', ' ').title(), "options": []}
        for option_value in sorted(list(options_set), key=lambda x: str(x)):
            # Find the display name
            name = str(option_value) # Default name
            for key, definition in all_definitions.items():
                if definition['group'] == group and definition.get('value', key) == option_value:
                    name = definition['name']
                    break
            manifest[group]["options"].append({"value": option_value, "name": name})
            
    return manifest

def group_and_finalize_logos(parsed_files):
    """Groups parsed files by their variants and builds the final 'logos' list."""
    grouped_logos = defaultdict(dict)
    for file_data in parsed_files:
        # Fill in missing optional variants with None for consistent grouping
        all_variant_keys = set(REQUIRED_BY_ASSET_TYPE['standard_logo']) | {'asset_type', 'division'}
        for key in all_variant_keys:
            if key not in file_data["raw_variants"]:
                file_data["raw_variants"][key] = None

        variant_key = tuple(sorted(file_data["raw_variants"].items()))
        
        _, file_ext = os.path.splitext(file_data["url"])
        format_key = 'all-formats' if file_ext.lower() == '.zip' else file_ext.lower().strip('.')
        if format_key:
            grouped_logos[variant_key][format_key] = file_data["url"]
            
    logos_list = [dict(variant_tuple, **{"links": links}) for variant_tuple, links in grouped_logos.items()]
    return sorted(logos_list, key=lambda x: str(x.get('division')) + str(x.get('asset_type')))


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
    variants_manifest = create_manifest(valid_files)
    print("Manifest created.")
    
    print("\n--- Phase 3: Grouping files and finalizing JSON ---")
    logos_list = group_and_finalize_logos(valid_files)
    
    final_data = {"variants": variants_manifest, "logos": logos_list}
    print(f"Processing complete. Found {len(logos_list)} unique logo combinations.")

    with open(OUTPUT_FILENAME, 'w', encoding='utf-8') as f:
        json.dump(final_data, f, indent=2, ensure_ascii=False)

    print(f"\n--- SUCCESS ---")
    print(f"Data file created as '{OUTPUT_FILENAME}'.")