import re
import json
import sys

ROW_RE = re.compile(
    r'^\|\s*`?\$([0-9A-Fa-f]{2,6})`?(?:.\s*`?\$([0-9A-Fa-f]{2,6})`?)?\s*\|'
    r'\s*([^|]+)\|\s*`?([^|`]+?)`?\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*$'
)


def parse(path):
    entries = []
    for line in open(path, encoding='utf-8'):
        line = line.rstrip('\n')
        m = ROW_RE.match(line)
        if not m:
            continue
        start_hex, end_hex, size, name, desc, users = m.groups()
        name = name.strip()
        if not name or name == 'Name':
            continue
        entries.append({
            'address': f'0x{start_hex.upper()}',
            'address_end': f'0x{end_hex.upper()}' if end_hex else None,
            'size': size.strip(),
            'name': name,
            'description': desc.strip(),
            'primary_users': users.strip(),
        })
    return entries


if __name__ == '__main__':
    entries = parse(sys.argv[1])
    json.dump(entries, open(sys.argv[2], 'w'), indent=1)
    print(f'parsed {len(entries)} WRAM entries', file=sys.stderr)
    named = sum(1 for e in entries if not e['name'][0].isupper() or '_' not in e['name'] and e['name'][0].islower())
    print(f'sample:', entries[:3], file=sys.stderr)
