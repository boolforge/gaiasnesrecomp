"""v2: consolidate every naming/documentation source now available,
including the major upstream update (db-us/ replacing us/, plus new
docs/wram-memory-map.md, docs/comments.json-equivalent, partNotes.json).

New in this pass, on top of build_symbols.py's original three sources:
- docs/wram-memory-map.md: 137 richly-described WRAM variables,
  cross-validated by the upstream author against DataCrystal's
  independent RAM map -- far richer than fixups.json's bare
  name/offset pairs (kept and merged, not replaced, since coverage
  isn't identical).
- db-us/partNotes.json: 45 paragraph-length function descriptions
  (purpose, calling context, COP usage).
- db-us/comments.json: 341 short inline annotations; 8 of which are
  explicit CPU-width statements ("Switch to 8-bit A", "16-bit A and
  X/Y for initialization") -- authoritative, human-verified M/X facts,
  distinct from and additional to this project's own lexically-derived
  ones.
"""
import json
import re
import pathlib
import sys

sys.path.insert(0, "/home/claude")
from parse_wram_map import parse as parse_wram_map

BASEROM = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else
                        "/home/claude/gaia_iog_baserom")
OUT_SYMBOLS = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else
                            "/home/claude/symbols_v2.json")
OUT_MX_COMMENTS = pathlib.Path(sys.argv[3] if len(sys.argv) > 3 else
                                "/home/claude/comment_mx_facts.json")

db_us = BASEROM / "db-us"
fixups = json.loads((db_us / "fixups.json").read_text()) if \
    (db_us / "fixups.json").exists() else {"mnemonics": {}}
part_notes = json.loads((db_us / "partNotes.json").read_text())
comments = json.loads((db_us / "comments.json").read_text())
wram_rows = parse_wram_map(BASEROM / "docs" / "wram-memory-map.md")

wram_vars = {name: {"wram_offset": offset, "wram_offset_hex": f"0x{offset:04X}"}
             for name, offset in fixups.get("mnemonics", {}).items()}
for row in wram_rows:
    wram_vars.setdefault(row["name"], {}).update({
        "address": row["address"], "address_end": row["address_end"],
        "size": row["size"], "description": row["description"],
        "primary_users": row["primary_users"],
    })

function_notes = {name: text for name, text in part_notes.items()}

# Explicit, human-authored CPU-width statements only -- a narrow,
# high-precision regex, not "any comment mentioning a number of bits",
# to avoid pulling in unrelated hits (checked against the false-positive
# candidates first: parameter values like "X=0 selects layer" do NOT
# match this pattern, only genuine mode-switch statements do).
WIDTH_RE = re.compile(
    r'\b(8-bit|16-bit)\s*A\b|\bSwitch to (8|16)-bit A\b|\bRestore (8|16)-bit A\b',
    re.I)
mx_comment_facts = {}
for addr_str, text in comments.items():
    m = WIDTH_RE.search(text)
    if not m:
        continue
    is_16 = '16' in (m.group(0))
    addr = int(addr_str)
    mx_comment_facts[addr] = {"m": 0 if is_16 else 1, "comment": text}

OUT_SYMBOLS.write_text(json.dumps({
    "wram_variables": wram_vars,
    "function_notes": function_notes,
}, indent=1, sort_keys=True))
OUT_MX_COMMENTS.write_text(json.dumps(
    {str(k): v for k, v in mx_comment_facts.items()}, indent=1))

print(f"wram_variables (merged): {len(wram_vars)}", file=sys.stderr)
print(f"function_notes: {len(function_notes)}", file=sys.stderr)
print(f"comment-derived M-state facts: {len(mx_comment_facts)}", file=sys.stderr)
for addr, v in mx_comment_facts.items():
    print(f"  {addr:06X}: m={v['m']}  ({v['comment'][:50]})", file=sys.stderr)
