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


def _first_nonblank_after(lines, idx):
    for j in range(idx + 1, len(lines)):
        s = lines[j].strip()
        if s:
            return s
    return None


def extract(asm_root: pathlib.Path):
    entries = []  # (bank, addr16, name, is_code, source_file)
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
            if remainder.startswith("{"):
                is_code = True
            elif remainder:
                is_code = False
            else:
                nxt = _first_nonblank_after(lines, i)
                is_code = bool(nxt) and nxt.startswith("{")

            name = f"{prefix}_{addr6}"
            key = (bank, addr16)
            if key in seen:
                dupes += 1
                continue
            seen[key] = True
            entries.append((bank, addr16, name, is_code, rel))

    print(f"asm files scanned: {len(asm_files)}", file=sys.stderr)
    print(f"entries extracted: {len(entries)}  "
          f"(code: {sum(1 for e in entries if e[3])}, "
          f"data: {sum(1 for e in entries if not e[3])})", file=sys.stderr)
    print(f"duplicate-address definitions skipped: {dupes}", file=sys.stderr)
    return entries


if __name__ == "__main__":
    asm_root = pathlib.Path(sys.argv[1])
    out_dir = pathlib.Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)

    entries = extract(asm_root)
    by_bank = defaultdict(list)
    for bank, addr16, name, is_code, src in entries:
        by_bank[bank].append((addr16, name, is_code))

    total_func = total_data = 0
    for bank in sorted(by_bank):
        items = sorted(by_bank[bank])
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
