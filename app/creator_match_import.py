"""Build the local creator-matching snapshot from the cleaned Excel export."""

import argparse
import gzip
import json
import os
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from creator_match import SNAPSHOT

SHEET = '达人信息全'
NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
HEADERS = ('达人账号', '达人名称', '一级分类', '二级分类',
           '粉丝数（个）', '新增粉丝数（个）', '达人等级', '达人画像')


def _rows(archive):
    # The cleaned export uses inline strings, but Excel may save them in a shared table.
    strings = []
    if 'xl/sharedStrings.xml' in archive.namelist():
        shared = ET.fromstring(archive.read('xl/sharedStrings.xml'))
        strings = [''.join(t.text or '' for t in item.iter(NS + 't')) for item in shared]
    with archive.open('xl/worksheets/sheet1.xml') as stream:
        for event, node in ET.iterparse(stream, events=('start', 'end')):
            if event == 'start' and node.tag == NS + 'sheetData':
                sheet = node
            if event != 'end' or node.tag != NS + 'row':
                continue
            values = {}
            for cell in node.iterfind(NS + 'c'):
                col = cell.get('r', '').rstrip('0123456789')
                cell_type = cell.get('t')
                value = cell.findtext(NS + 'v', '')
                if cell_type == 's':
                    value = strings[int(value)]
                elif cell_type == 'inlineStr':
                    value = ''.join(t.text or '' for t in cell.iter(NS + 't'))
                values[col] = value
            yield int(node.get('r')), tuple(values.get(col, '') for col in 'ABCDEFGH')
            sheet.remove(node)


def build_snapshot(source, destination=SNAPSHOT):
    """Import identifiers as strings and retain only fields used by matching."""
    source, destination = Path(source), Path(destination)
    seen = set()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=destination.parent)
    os.close(fd)
    try:
        with ZipFile(source) as archive, gzip.open(temporary, 'wt', encoding='utf-8') as output:
            rows = _rows(archive)
            if next(rows, (None, ())) != (1, HEADERS):
                raise ValueError('达人信息全字段与清洗版不一致')
            output.write(json.dumps({'name': source.name, 'sheet': SHEET}, ensure_ascii=False) + '\n')
            for number, (handle, name, category, _, _, _, _, payload) in rows:
                if not handle or not name or handle in seen:
                    raise ValueError(f'第 {number} 行达人账号重复或缺失资料')
                profile = json.loads(payload)
                if profile['达人账号'] != handle or profile['达人名称'] != name:
                    raise ValueError(f'第 {number} 行的画像与主表不一致')
                seen.add(handle)
                categories = [part.strip() for part in category.split('，') if part.strip()]
                data = [number, handle, name, categories, profile['领域分类'], profile['带货类型']]
                output.write(json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n')
        if not seen:
            raise ValueError('达人源表没有记录')
        os.chmod(temporary, 0o644)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return len(seen)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workbook', type=Path)
    args = parser.parse_args()
    print(f'导入 {build_snapshot(args.workbook):,} 个达人账号至 {SNAPSHOT}')
