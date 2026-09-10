"""Replace both parts.json (removed upstream) and blocks.json (schema
changed in a way that merges distinct data+code spans -- see
docs/FINDINGS.md, "actor_def / thinker_def") with a direct extraction
from GaiaPacker's own real --unpack disassembly output.

This is the same label-detection approach used since this project's
first script (a label opens a `{` block for code or a `[` block for
data -- Gaia's own DSL syntax, not a name-based guess), just run
against the complete 806-file corpus instead of IOGRetranslation's
133 patch-only files. Verified directly against the actor_def
ambiguity that motivated this rewrite: `head_00D0D1 [...]` (3-byte
h_actor data) and `func_00D0D4 {...}` (a separate, immediately-
following code block) come out as two distinct, correctly-typed
entries here, exactly matching the real file -- the blocks.json
schema had merged them into one ambiguous `actor_def` span.
"""
import re
import sys
import pathlib
from collections import defaultdict

LABEL_DEF_RE = re.compile(
    r'^([A-Za-z_][A-Za-z0-9_]*)_([0-9A-Fa-f]{6})\b[ \t]*(.*)$'
)
_SKIP_DIR_PARTS = {".git", ".github", "node_modules"}

# Real 65816 control-transfer mnemonics that end a fallthrough chain.
# A code block whose last recognized instruction line isn't one of
# these does not actually terminate -- execution continues straight
# into whatever the next declared label happens to be. Verified
# directly against a real example: `code_03DA00 { STZ $0654 }` has no
# terminator and genuinely falls through into `code_03DA03`.
_TERMINATOR_MNEMONICS = {
    "RTS", "RTL", "RTI", "STP", "WAI", "BRA", "BRL", "JMP", "JML",
}
_MNEM_LINE_RE = re.compile(r'^([A-Za-z]{2,4})\b')


def _first_nonblank_after(lines, idx):
    for j in range(idx + 1, len(lines)):
        s = lines[j].strip()
        if s:
            return s
    return None


def _block_ends_in_terminator(lines, start_idx):
    """Scan a `{ ... }` block (starting the line after its opener) and
    return whether the last recognizable mnemonic line is a real
    terminator. Conservative: an unrecognized last line (label
    references, directives) counts as "not a terminator", since a
    merge is only ever a widening of an existing func's end -- never
    narrower than what extraction would otherwise produce -- so a
    wrong guess here just under-merges rather than corrupting a
    boundary."""
    depth = 1
    last_mnem = None
    j = start_idx
    while j < len(lines) and depth > 0:
        raw = lines[j].strip()
        if raw == "{":
            depth += 1
        elif raw == "}":
            depth -= 1
            j += 1
            continue
        else:
            m = _MNEM_LINE_RE.match(raw)
            if m:
                last_mnem = m.group(1)
        j += 1
    return last_mnem in _TERMINATOR_MNEMONICS


def extract(asm_root: pathlib.Path):
    entries = []  # (bank, addr16, name, is_code, has_terminator, source_file)
    seen = {}
    dupes = 0

    asm_files = sorted(
        p for p in asm_root.rglob("*.asm")
        if not any(part in _SKIP_DIR_PARTS for part in p.parts)
    )

    for path in asm_files:
        rel = str(path.relative_to(asm_root))
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()

        for i, raw_line in enumerate(lines):
            m = LABEL_DEF_RE.match(raw_line)
            if not m:
                continue
            prefix, addr6, remainder = m.groups()
            addr24 = int(addr6, 16)
            bank = (addr24 >> 16) & 0xFF
            addr16 = addr24 & 0xFFFF

            remainder = remainder.strip()
            has_terminator = True  # only meaningful for is_code below
            if remainder.startswith("{"):
                is_code = True
                has_terminator = _block_ends_in_terminator(lines, i + 1)
            elif remainder:
                is_code = False
            else:
                nxt = _first_nonblank_after(lines, i)
                is_code = bool(nxt) and nxt.startswith("{")
                if is_code:
                    has_terminator = _block_ends_in_terminator(lines, i + 1)

            name = f"{prefix}_{addr6}"
            key = (bank, addr16)
            if key in seen:
                dupes += 1
                continue
            seen[key] = True
            entries.append((bank, addr16, name, is_code, has_terminator, rel))

    print(f"asm files scanned: {len(asm_files)}", file=sys.stderr)
    print(f"entries extracted: {len(entries)}  "
          f"(code: {sum(1 for e in entries if e[3])}, "
          f"data: {sum(1 for e in entries if not e[3])})", file=sys.stderr)
    print(f"duplicate-address definitions skipped: {dupes}", file=sys.stderr)
    return entries


def entries_to_bank_items(entries):
    """Group raw extract() entries by bank and merge fallthrough-only
    code runs into single func spans. Returns {bank: [(addr16, name,
    is_code), ...]} with fallthrough sub-labels already folded in --
    shared by this script's own CLI and by build_cfg_v4.py so both
    apply the identical merge logic."""
    by_bank = defaultdict(list)
    for bank, addr16, name, is_code, has_terminator, src in entries:
        by_bank[bank].append((addr16, name, is_code, has_terminator))

    merged = {}
    total_merged_away = 0
    for bank in sorted(by_bank):
        items = sorted(by_bank[bank])
        out = []
        idx = 0
        while idx < len(items):
            off_s, name, is_code, has_terminator = items[idx]
            if not is_code:
                out.append((off_s, name, is_code))
                idx += 1
                continue
            run_end_idx = idx
            while (run_end_idx < len(items) and items[run_end_idx][2]
                   and not items[run_end_idx][3]
                   and run_end_idx + 1 < len(items)
                   and items[run_end_idx + 1][2]):
                run_end_idx += 1
            out.append((off_s, name, is_code))
            total_merged_away += run_end_idx - idx
            idx = run_end_idx + 1
        merged[bank] = out
    print(f"fallthrough-only labels merged into their predecessor's func: "
          f"{total_merged_away}", file=sys.stderr)
    return merged


if __name__ == "__main__":
    asm_root = pathlib.Path(sys.argv[1])
    out_dir = pathlib.Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    entries = extract(asm_root)
    by_bank = entries_to_bank_items(entries)

    total_func = total_data = 0
    for bank in sorted(by_bank):
        items = by_bank[bank]
        lines = [f"bank = {bank:02x}", ""]
        for idx, (off_s, name, is_code) in enumerate(items):
            off_e = items[idx + 1][0] if idx + 1 < len(items) else 0x10000
            if is_code:
                lines.append(f"func {name} {off_s:04x} end:{off_e:04x}")
                total_func += 1
            else:
                lines.append(f"data_region {bank:02x} {off_s:04x} {off_e:04x}")
                total_data += 1
        (out_dir / f"bank{bank:02x}.cfg").write_text("\n".join(lines) + "\n")
    print(f"func: {total_func}  data_region: {total_data}  "
          f"banks: {len(by_bank)}", file=sys.stderr)
