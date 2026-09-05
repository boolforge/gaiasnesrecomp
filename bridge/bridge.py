#!/usr/bin/env python3
"""bridge.py — Azarem/gaia-iog-baserom -> snesrecomp v2 cfg pipeline.

Single entry point that reproduces every verified step from this
project's development history in one deterministic pass:

  1. Read us/parts.json (a complete, whole-ROM start/end/struct export
     from GaiaLabs' own extraction of Illusion of Gaia) as the base
     structural truth.
  2. Apply verified corrections from us/overrides.json:
       - name overrides (90/91 differ from parts.json in this
         checkout; applied directly)
       - the 19 M-only width overrides, via snesrecomp's own
         `entry_mx_at` cfg directive (X=1 filled in as a disclosed,
         evidence-based assumption -- see README, section "What's
         assumed vs. verified")
     The 27 type overrides and the single {"B": 126} entry are
     deliberately NOT applied -- the former already match parts.json
     exactly (checked; a no-op), the latter maps to no known cfg
     mechanism (left alone rather than guessed).
  3. Emit one snesrecomp v2 bankNN.cfg per bank.
  4. Emit cop_widths.json: all 209/209 Illusion of Gaia COP command
     operand widths, computed from us/copdef.json using the exact
     byte-width rules in GaiaLabs' own gaia-core source
     (src/rom/extraction/cop.ts + src/types/addressing.ts), for use
     with the snesrecomp decoder patch in patches/.

This script only ever reads Gaia's own already-published JSON exports
and the snesrecomp cfg grammar. It does not read or require the game
ROM -- the ROM is only needed later, by snesrecomp's own
tools/v2_analyze.py, to actually run the analysis this cfg feeds.

Usage:
    python bridge.py --baserom /path/to/gaia-iog-baserom/us \\
                      --out-cfg ./cfg --out-cop-widths ./cop_widths.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import defaultdict


# ---------------------------------------------------------------------------
# Step 1-3: parts.json + overrides.json -> bankNN.cfg
# ---------------------------------------------------------------------------

def build_cfg(baserom: pathlib.Path, out_dir: pathlib.Path) -> None:
    parts = json.loads((baserom / "parts.json").read_text())
    overrides = json.loads((baserom / "overrides.json").read_text())

    name_fixes = {int(k): v["name"] for k, v in overrides.items()
                  if list(v.keys()) == ["name"]}
    m_fixes = {int(k): v["M"] for k, v in overrides.items()
               if list(v.keys()) == ["M"]}
    skipped = {k: v for k, v in overrides.items()
               if list(v.keys()) not in (["name"], ["type"], ["M"])}

    by_bank = defaultdict(list)
    applied_names = 0
    for p in parts:
        start, end, name, struct = p["start"], p["end"], p["name"], p["struct"]
        if start in name_fixes and name_fixes[start] != name:
            name = name_fixes[start]
            applied_names += 1
        bank = start >> 16
        off_s = start & 0xFFFF
        off_e = end & 0xFFFF if (end >> 16) == bank else 0x10000
        by_bank[bank].append((off_s, off_e, name, struct == "Code", struct))

    mx_by_bank = defaultdict(list)
    for addr, m_val in m_fixes.items():
        mx_by_bank[addr >> 16].append((addr & 0xFFFF, m_val))

    out_dir.mkdir(parents=True, exist_ok=True)
    total_func = total_data = 0
    for bank in sorted(by_bank):
        items = sorted(by_bank[bank])
        lines = [f"bank = {bank:02x}", ""]
        for off16, m_val in sorted(mx_by_bank.get(bank, [])):
            lines.append(f"entry_mx_at {off16:04x} {m_val} 1  "
                          f"# overrides.json M-fix; X=1 assumed, see README")
        if mx_by_bank.get(bank):
            lines.append("")
        for off_s, off_e, name, is_code, struct in items:
            if is_code:
                lines.append(f"func {name} {off_s:04x} end:{off_e:04x}")
                total_func += 1
            else:
                lines.append(
                    f"data_region {bank:02x} {off_s:04x} {off_e:04x}  # {struct}")
                total_data += 1
        (out_dir / f"bank{bank:02x}.cfg").write_text("\n".join(lines) + "\n")

    print(f"[cfg] banks: {len(by_bank)}  func: {total_func}  "
          f"data_region: {total_data}", file=sys.stderr)
    print(f"[cfg] name corrections applied: {applied_names}/{len(name_fixes)}  "
          f"entry_mx_at facts: {sum(len(v) for v in mx_by_bank.values())}/"
          f"{len(m_fixes)}", file=sys.stderr)
    if skipped:
        print(f"[cfg] overrides.json entries with no matching cfg mechanism "
              f"(NOT applied, not guessed): {skipped}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Step 4: copdef.json -> cop_widths.json
# ---------------------------------------------------------------------------

def _member_width(part: str) -> "int | None":
    """Byte width of one COP operand part-token, per GaiaLabs'
    getMemberTypeSize() (gaia-core src/rom/extraction/cop.ts) and the
    sigil->AddressType table in src/types/addressing.ts."""
    if part == "Byte":
        return 1
    if part == "Word":
        return 2
    if part == "Address":
        return 3
    sigil = part[0]
    return {"&": 2, "@": 3, "^": 1, "*": 1}.get(sigil)


def build_cop_widths(baserom: pathlib.Path, out_path: pathlib.Path) -> None:
    cop = json.loads((baserom / "copdef.json").read_text())
    table = {}
    unresolved = []
    for name, v in cop.items():
        total = 1  # the id byte itself
        ok = True
        for part in v["parts"]:
            w = _member_width(part)
            if w is None:
                ok = False
                break
            total += w
        if ok:
            table[str(v["id"])] = {
                "name": name,
                "total_operand_bytes": total,
                "halt": bool(v.get("halt", False)),
            }
        else:
            unresolved.append((name, v["parts"]))

    out_path.write_text(json.dumps(table, indent=1, sort_keys=True))
    print(f"[cop] resolved {len(table)}/{len(cop)} command widths",
          file=sys.stderr)
    if unresolved:
        print(f"[cop] unresolved (excluded, not guessed): {unresolved}",
              file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baserom", required=True, type=pathlib.Path,
                     help="path to a gaia-iog-baserom checkout's us/ (or jp/) dir")
    ap.add_argument("--out-cfg", required=True, type=pathlib.Path)
    ap.add_argument("--out-cop-widths", required=True, type=pathlib.Path)
    args = ap.parse_args()

    build_cfg(args.baserom, args.out_cfg)
    build_cop_widths(args.baserom, args.out_cop_widths)
    return 0


if __name__ == "__main__":
    sys.exit(main())
