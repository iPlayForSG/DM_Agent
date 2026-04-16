"""Utility script for extracting the inline spell database into backend/data."""

import json
import re
import os

def extract_spells():
    source_path = os.path.join(os.path.dirname(__file__), '..', 'test.json')
    dest_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'spells.json')

    with open(source_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # The source dump stores spells inside a single inline JSON script tag.
    match = re.search(r'<script id="spell-db-inline" type="application/json">(.*?)</script>', content, re.DOTALL)

    if match:
        json_str = match.group(1)
        try:
            data = json.loads(json_str)
            # Keep the extracted file human-readable for future diffs.
            with open(dest_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"Successfully extracted spell database to {dest_path}")
        except json.JSONDecodeError as e:
            print(f"JSON Decode Error: {e}")
    else:
        print("Could not find spell-db-inline script tag.")

if __name__ == "__main__":
    extract_spells()
