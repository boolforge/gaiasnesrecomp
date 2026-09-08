"""Consolidate every human-authored naming source in the Gaia ecosystem
into one symbols.json, keyed cleanly by address space, for use when
this bridge eventually reaches code generation. Mechanical only --
every name here is copied verbatim from an upstream source, nothing
invented.

Sources merged (all from gaia-iog-baserom/us/ unless noted):
- fixups.json["mnemonics"]: 221 named WRAM variables (e.g.
  "camera_offset_x" @ $1750). Decimal offsets are WRAM-relative, NOT
  ROM addresses -- a completely different space from everything else
  this bridge has used so far (all prior work only named ROM
  code/data). Written out with an explicit wram_offset field rather
  than folded into the ROM address namespace, so nothing downstream
  can mix the two spaces by accident.
- names.json: 413 ROM-address names, mostly hardware vectors/entry
  points (e.g. "ResetVector" @ 0x8000).
- scenes.json: 228 named game areas/rooms, with both a slug and a
  human description (e.g. "south-cape" / "South Cape").
- The real GaiaPacker asm/ corpus's own labels (already the primary
  naming source for every func/data_region emitted by
  extract_from_asm_corpus.py) are NOT duplicated here -- this file is
  specifically the naming gaia-iog-baserom's JSON exports add on top
  of what the real corpus already names.
"""
import json
import pathlib
import sys

BASEROM = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else
                        "/home/claude/gaia_iog_baserom/us")
OUT = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else
                    "/home/claude/symbols.json")

fixups = json.loads((BASEROM / "fixups.json").read_text())
names = json.loads((BASEROM / "names.json").read_text())
scenes = json.loads((BASEROM / "scenes.json").read_text())

wram_vars = {name: {"wram_offset": offset, "wram_offset_hex": f"0x{offset:04X}"}
             for name, offset in fixups.get("mnemonics", {}).items()}

rom_names = {}
for addr_str, name in names.items():
    addr = int(addr_str)
    rom_names[f"{addr:06X}"] = {
        "name": name,
        "bank": f"{addr >> 16:02X}",
        "offset": f"{addr & 0xFFFF:04X}",
    }

scene_names = {s["name"]: {"group": s["group"], "index": s["index"],
                            "description": s["description"]}
               for s in scenes}

out = {
    "wram_variables": wram_vars,
    "rom_names": rom_names,
    "scenes": scene_names,
}
OUT.write_text(json.dumps(out, indent=1, sort_keys=True))
print(f"wram_variables: {len(wram_vars)}", file=sys.stderr)
print(f"rom_names: {len(rom_names)}", file=sys.stderr)
print(f"scenes: {len(scene_names)}", file=sys.stderr)
