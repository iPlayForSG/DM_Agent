"""将历史内嵌法表导入单一完整目录；不再生成独立 spells.json。"""
import json
from pathlib import Path
import re

try:
    from .merge_spell_catalogs import merge_catalogs
except ImportError:
    from merge_spell_catalogs import merge_catalogs


def extract_spells(source_path=None, dest_path=None):
    backend = Path(__file__).resolve().parents[1]
    source = Path(source_path) if source_path else backend/'test.json'
    destination = Path(dest_path) if dest_path else backend/'data/spell_catalog_2024.json'
    # 历史HTML通常只有低环法术，不能直接覆盖完整的2024目录。
    current = json.loads(destination.read_text(encoding='utf-8'))
    content = source.read_text(encoding='utf-8')
    match = re.search(r'<script id="spell-db-inline" type="application/json">(.*?)</script>',content,re.DOTALL)
    if not match:
        raise ValueError('Could not find spell-db-inline script tag')
    result = merge_catalogs(current,json.loads(match[1]))
    destination.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Successfully merged spell database into {destination}')


if __name__ == '__main__':
    extract_spells()
