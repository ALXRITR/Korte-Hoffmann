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
# SINGLE SOURCE OF TRUTH
# ==============================================================================

BRAND_CANON = [
    "KH-Architekten+Ingenieure",
    "KH-Gebaeudedruck",
    "KH-Gruppe",
    "KH-Immobilien",
    "KORTE-HOFFMANN",
]

ASSET_TYPE_KEYS = {
    # Division slugs (standard logos with lockups + bar)
    "architekten+ingenieure": {"name": "Architekten+Ingenieure", "type": "standard_logo"},
    "gebaeudedruck": {"name": "Gebäudedruck", "type": "standard_logo"},
    "gruppe": {"name": "Gruppe", "type": "standard_logo"},
    "immobilien": {"name": "Immobilien", "type": "standard_logo"},

    # Special cases
    "korte-hoffmann": {"name": "Korte-Hoffmann", "type": "korte_hoffmann_logotype"},
    "dreihaus": {"name": "Dreihaus", "type": "dreihaus_logo"},
    "favicon": {"name": "Favicon", "type": "favicon"},
    "monogram": {"name": "Monogram", "type": "monogram"},
}

VARIANT_PART_DEFINITIONS = {
    # Size variants
    "size-xxs": {"group": "optical_size", "value": "xxs", "name": "Extra Extra Small"},
    "size-m":   {"group": "optical_size", "value": "m", "name": "Medium"},
    "size-xxl": {"group": "optical_size", "value": "xxl", "name": "Extra Extra Large"},

    # Legacy size mapping
    "size-s": {"group": "optical_size", "value": "xxs", "name": "Small (Legacy)"},
    "size-l": {"group": "optical_size", "value": "xxl", "name": "Large (Legacy)"},

    # Color
    "black": {"group": "color", "name": "Black"},
    "white": {"group": "color", "name": "White"},
    "black+accent": {"group": "color", "name": "Black+Accent"},
    "white+accent": {"group": "color", "name": "White+Accent"},

    # Lockups (only for standard_logo types)
    "center": {"group": "lockup", "name": "Center"},
    "left": {"group": "lockup", "name": "Left"},
    "right": {"group": "lockup", "name": "Right"},
    "center-compact": {"group": "lockup", "name": "Center-Compact"},
    # "no-lockup" removed in new scheme; still recognized below if ever present, but treated as invalid for standard logos.

    # Bar (filenames have positive token only; False inferred)
    "bar": {"group": "bar", "value": True, "name": "Bar"},
    "no-bar": {"group": "bar", "value": False, "name": "No Bar"},  # legacy mapping / naming aid

    # Compact only for KORTE-HOFFMANN; filenames use positive token only
    "compact": {"group": "compact", "value": True, "name": "Compact"},
    "no-compact": {"group": "compact", "value": False, "name": "No Compact"},  # legacy mapping / naming aid

    # Trademark and Clearspace (filenames positive only; False inferred)
    "trademark": {"group": "trademark", "value": True, "name": "With ®"},
    "no-trademark": {"group": "trademark", "value": False, "name": "Without ®"},
    "clearspace": {"group": "clearspace", "value": True, "name": "With Clearspace"},
    "no-clearspace": {"group": "clearspace", "value": False, "name": "Without Clearspace"},

    # Modifiers
    "rgb": {"group": "modifier"},
    "cmyk": {"group": "modifier"},
}

# Required groups per asset type (optional booleans are inferred if missing)
REQUIRED_BY_ASSET_TYPE = {
    "standard_logo": {"division", "optical_size", "color", "lockup"},
    "korte_hoffmann_logotype": {"division", "optical_size", "color", "compact"},
    "dreihaus_logo": {"optical_size", "color"},
    "monogram": {"color"},
    "favicon": {"color"},
}

def get_all_file_urls(owner, repo, path=""):
    api_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/main?recursive=1"
    response = requests.get(api_url, headers={'Accept': 'application/vnd.github.v3+json'})
    if response.status_code != 200:
        return []
    tree = response.json().get('tree', [])
    ignore_patterns = ['.py', '.json', '.csv', '.DS_Store', '.git', 'README']
    urls = [
        f"https://raw.githubusercontent.com/{owner}/{repo}/main/{unquote(item['path'])}"
        for item in tree
        if item['type'] == 'blob'
        and item['path'].startswith(path + '/')
        and not any(p in item['path'] for p in ignore_patterns)
    ]
    return urls

def parse_and_validate_files(urls):
    parsed_files, ignored_log = [], []

    # consider all slugs that can start a filename except pure special keywords
    sorted_brand_keys = sorted(
        [k for k in ASSET_TYPE_KEYS.keys() if k not in {"favicon", "monogram"}],
        key=len, reverse=True
    )

    for url in urls:
        filename, _ = os.path.splitext(os.path.basename(url))

        # Ignore top-level brand ZIPs
        if filename in BRAND_CANON:
            ignored_log.append({'file': filename, 'reason': "Ignoring top-level brand ZIP file."})
            continue

        parts_str = filename.lower().replace('kh-', '')
        raw_variants, unmatched = {}, []

        # Step 1: brand/base asset detection
        brand_key = None
        for key in sorted_brand_keys:
            if parts_str.startswith(key):
                brand_key = key
                break

        # Step 2: asset type decision
        asset_key_hint = None
        if 'favicon' in parts_str:
            asset_key_hint = 'favicon'
        elif 'monogram' in parts_str:
            asset_key_hint = 'monogram'

        if asset_key_hint:
            asset_type = ASSET_TYPE_KEYS[asset_key_hint]['type']  # 'favicon' or 'monogram'
        elif brand_key == 'korte-hoffmann':
            asset_type = 'korte_hoffmann_logotype'
        elif brand_key == 'dreihaus':
            asset_type = 'dreihaus_logo'
        elif brand_key in {'architekten+ingenieure','gebaeudedruck','gruppe','immobilien'}:
            asset_type = 'standard_logo'
        else:
            ignored_log.append({'file': filename, 'reason': "Could not identify a known brand or asset type."})
            continue

        raw_variants['asset_type'] = asset_type

        # division
        if asset_type in {'standard_logo', 'korte_hoffmann_logotype'} and brand_key:
            raw_variants['division'] = brand_key
        elif asset_key_hint in {'favicon','monogram'} and brand_key and brand_key != asset_key_hint:
            raw_variants['division'] = brand_key  # e.g. korte-hoffmann_monogram_...

        # Step 3: parse remaining parts
        remaining_str = parts_str[len(brand_key):].strip('_') if brand_key else parts_str
        remaining_parts = remaining_str.split('_') if remaining_str else []

        for part in remaining_parts:
            if not part:
                continue

            # Legacy compact mapping for non-KH: map to lockups
            if part == 'compact' and asset_type == 'standard_logo':
                raw_variants['lockup'] = 'center-compact'
                continue
            if part == 'no-compact' and asset_type == 'standard_logo':
                raw_variants['lockup'] = 'center'
                continue

            if part in VARIANT_PART_DEFINITIONS:
                definition = VARIANT_PART_DEFINITIONS[part]
                group = definition['group']
                value = definition.get('value', part)

                # Only record 'compact' as a group for KORTE-HOFFMANN
                if group == 'compact' and asset_type != 'korte_hoffmann_logotype':
                    # ignore, handled above for legacy mapping
                    continue

                # For bar/trademark/clearspace we only see positives in filenames
                # Missing means False; we set defaults below.
                raw_variants[group] = value
            else:
                # tolerate unknowns but report
                if part not in ASSET_TYPE_KEYS:
                    unmatched.append(part)

        # Step 4: fill defaults for optional booleans based on asset type
        if asset_type == 'standard_logo':
            raw_variants.setdefault('bar', False)
            raw_variants.setdefault('trademark', False)
            raw_variants.setdefault('clearspace', False)
        elif asset_type == 'korte_hoffmann_logotype':
            raw_variants.setdefault('compact', False)
            raw_variants.setdefault('trademark', False)
            raw_variants.setdefault('clearspace', False)
        elif asset_type == 'dreihaus_logo':
            raw_variants.setdefault('trademark', False)
            raw_variants.setdefault('clearspace', False)

        # Step 5: validate
        required = REQUIRED_BY_ASSET_TYPE.get(asset_type, set())
        missing = required - set(raw_variants.keys())

        # Guardrail: standard_logo must not declare "no-lockup"
        if asset_type == 'standard_logo' and 'no-lockup' in remaining_parts:
            unmatched.append('no-lockup')

        if missing or unmatched:
            reasons = []
            if missing:
                reasons.append(f"Missing required variants for asset_type '{asset_type}': {sorted(list(missing))}")
            if unmatched:
                reasons.append(f"Found unmatched parts: {unmatched}")
            ignored_log.append({'file': filename, 'reason': '; '.join(reasons)})
        else:
            parsed_files.append({"url": url, "raw_variants": raw_variants})

    return parsed_files, ignored_log

def create_manifest(parsed_files):
    discovered = defaultdict(set)
    for file_data in parsed_files:
        for group, value in file_data["raw_variants"].items():
            # exclude modifier from manifest
            if group == "modifier":
                continue
            discovered[group].add(value)

    # Build name lookups
    all_defs = {k: v for k, v in VARIANT_PART_DEFINITIONS.items()}
    for k, v in ASSET_TYPE_KEYS.items():
        group_name = "division" if v.get('type') in {"standard_logo", "korte_hoffmann_logotype"} else "asset_type"
        all_defs[k] = {"group": group_name, "name": v['name']}

    # Add friendly names for False booleans if not hit via legacy tokens
    all_defs.setdefault("__bar_false__", {"group": "bar", "value": False, "name": "No Bar"})
    all_defs.setdefault("__tm_false__", {"group": "trademark", "value": False, "name": "Without ®"})
    all_defs.setdefault("__cs_false__", {"group": "clearspace", "value": False, "name": "Without Clearspace"})
    all_defs.setdefault("__khc_false__", {"group": "compact", "value": False, "name": "No Compact"})

    manifest = {}
    for group, options in sorted(discovered.items()):
        if group == 'modifier':
            continue
        manifest[group] = {"name": group.replace('_', ' ').title(), "options": []}
        for option in sorted(list(options), key=lambda x: str(x)):
            name = str(option)
            # human-readable name from defs
            for k, v in all_defs.items():
                if v.get('group') == group and v.get('value', k) == option:
                    name = v['name']
                    break
            manifest[group]["options"].append({"value": option, "name": name})
    return manifest

def group_and_finalize_logos(parsed_files):
    grouped_logos = defaultdict(dict)
    for file_data in parsed_files:
        rv = file_data["raw_variants"]
        # Variant key excludes color-mode modifier so RGB/CMYK map to same variant
        variant_items = [(k, v) for k, v in rv.items() if k != "modifier"]
        variant_key = tuple(sorted(variant_items))

        _, file_ext = os.path.splitext(file_data["url"])
        ext_key = file_ext.lower().strip('.')
        if file_ext.lower() == '.zip':
            format_key = 'all-formats'
        else:
            mode = rv.get("modifier")
            format_key = f"{ext_key}_{mode}" if mode else ext_key

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
