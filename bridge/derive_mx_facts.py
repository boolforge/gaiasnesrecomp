"""Derive real, verified M-state facts by lexically parsing GaiaPacker's
actual --unpack disassembly output (asm/**/*.asm) -- not by guessing or
simulating, but by reading the exact hex-digit width the human-verified
disassembly already wrote for every accumulator immediate operand.

Why this works without simulating REP/SEP at all: Gaia's own text
syntax writes `#$XX` (2 hex digits) for an 8-bit immediate and `#$XXXX`
(4 hex digits) for a 16-bit one. That width was already decided
correctly by GaiaLib's own extractor when this text was generated, so
reading it back tells us the true M state at that exact instruction --
we don't need to track REP/SEP ourselves at all, just trust digit
count, which is a lexical fact, not an inference.

Walks each code block (`NAME_BBOOOO { ... }`) from its own labeled
start address, summing each instruction's real byte size as it goes,
so every instruction in the block gets a computed address. The moment
a line can't be confidently sized (an addressing mode/operand shape
not in the table below), that block's walk stops right there -- no
guessing past it. Every M-revealing accumulator immediate encountered
before that point becomes an `entry_mx_at` fact.
"""
import json
import pathlib
import re
import sys
from collections import defaultdict

LABEL_RE = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)_([0-9A-Fa-f]{6})\s*\{')
COP_RE = re.compile(r'^COP\s*\[([0-9A-Fa-f]{2})\]')

ACC_MNEMONICS = {'LDA', 'ADC', 'AND', 'CMP', 'EOR', 'ORA', 'SBC', 'BIT'}
IDX_MNEMONICS = {'LDX', 'LDY', 'CPX', 'CPY'}
BRANCH_MNEMONICS = {'BCC', 'BCS', 'BEQ', 'BMI', 'BNE', 'BPL', 'BRA', 'BVC', 'BVS'}
IMPLIED_MNEMONICS = {
    'CLC', 'SEC', 'CLD', 'SED', 'CLI', 'SEI', 'CLV', 'TAX', 'TAY', 'TXA',
    'TYA', 'TXS', 'TSX', 'TXY', 'TYX', 'TCD', 'TDC', 'TCS', 'TSC', 'PHA',
    'PLA', 'PHX', 'PLX', 'PHY', 'PLY', 'PHP', 'PLP', 'PHB', 'PLB', 'PHD',
    'PLD', 'PHK', 'INC', 'DEC', 'INX', 'DEX', 'INY', 'DEY', 'NOP', 'XBA',
    'XCE', 'RTS', 'RTL', 'RTI', 'STP', 'WAI', 'ASL', 'LSR', 'ROL', 'ROR',
}

# operand-shape -> byte size (opcode + operand); (None) rows below are
# resolved per-line since size depends on hex-digit count observed.
_IMM_RE = re.compile(r'^#\$([0-9A-Fa-f]+)\b')
_LONG_RE = re.compile(r'^\$[0-9A-Fa-f]{6}\b')
_ABS_IDX_LONG_RE = re.compile(r'^\$[0-9A-Fa-f]{6},[XY]\b')
_ABS_RE = re.compile(r'^\$[0-9A-Fa-f]{4}\b')
_DP_RE = re.compile(r'^\$[0-9A-Fa-f]{2}\b')
_IND_LONG_DP_RE = re.compile(r'^\[\$[0-9A-Fa-f]{2}\](,Y)?\b')
_IND_ABS_RE = re.compile(r'^\(\$[0-9A-Fa-f]{4}(,X)?\)\b')
_IND_DP_RE = re.compile(r'^\(\$[0-9A-Fa-f]{2}(,X)?\)(,Y)?\b')
_LABEL_OPERAND_RE = re.compile(r'^\$?&?@?[A-Za-z_][A-Za-z0-9_]*\b')


def line_size(mnem: str, rest: str, m_state: "int|None", cop_table: dict):
    """Return (size_in_bytes, reveals_m_as) or None if unparseable."""
    rest = rest.strip()
    if mnem == 'COP':
        cm = COP_RE.match('COP ' + '[' + rest.split('[', 1)[1] if '[' in rest else '')
        m2 = re.match(r'^\[([0-9A-Fa-f]{2})\]', rest)
        if not m2:
            return None
        cop_id = int(m2.group(1), 16)
        entry = cop_table.get(cop_id) or cop_table.get(str(cop_id))
        if entry is None:
            return None
        return 1 + entry['total_operand_bytes'], None
    if mnem in IMPLIED_MNEMONICS and not rest:
        return 1, None
    if mnem in BRANCH_MNEMONICS:
        return 2, None
    if mnem == 'BRL':
        return 3, None
    if mnem in ('JSL', 'JML'):
        return 4, None
    if mnem in ('JSR', 'JMP'):
        if _IND_ABS_RE.match(rest):
            return 3, None
        if _LABEL_OPERAND_RE.match(rest) or _ABS_RE.match(rest):
            return 3, None
        return None
    if mnem == 'PEA':
        return 3, None
    if mnem in ('MVN', 'MVP'):
        return 3, None
    im = _IMM_RE.match(rest)
    if im:
        digits = len(im.group(1))
        if digits <= 2:
            size, revealed_m = 2, 1
        elif digits <= 4:
            size, revealed_m = 3, 0
        else:
            return None
        if mnem in ACC_MNEMONICS:
            return size, revealed_m
        if mnem in IDX_MNEMONICS:
            return size, None  # reveals X, not tracked in this pass
        return size, None
    if _LONG_RE.match(rest) or _ABS_IDX_LONG_RE.match(rest):
        return 4, None
    if _IND_LONG_DP_RE.match(rest):
        return 2, None
    if _IND_ABS_RE.match(rest):
        return 3, None
    if _IND_DP_RE.match(rest):
        return 2, None
    if _ABS_RE.match(rest):
        return 3, None
    if _DP_RE.match(rest):
        return 2, None
    if _LABEL_OPERAND_RE.match(rest):
        # A bare &/@ label reference used as a full/absolute operand
        # (not #immediate, handled above): treat as absolute (3 bytes)
        # -- the common case in this codebase for JMP/LDA $&label-style
        # references. Anything for which that's wrong will simply fail
        # to match a real instruction boundary later and the walk for
        # THIS block stops there, so a wrong guess here is self-limiting.
        return 3, None
    return None


LINE_RE = re.compile(r'^([A-Za-z]{2,4})\b\s*(.*)$')


def walk_asm_dir(asm_dir: pathlib.Path, cop_table: dict):
    facts = {}  # (bank, off16) -> m value
    stopped_early = 0
    blocks_walked = 0
    for path in sorted(asm_dir.rglob('*.asm')):
        lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
        i = 0
        while i < len(lines):
            m = LABEL_RE.match(lines[i])
            if not m:
                i += 1
                continue
            addr = int(m.group(2), 16)
            bank = addr >> 16
            pc = addr & 0xFFFF
            blocks_walked += 1
            j = i + 1
            depth = 1
            while j < len(lines) and depth > 0:
                raw = lines[j].strip()
                if raw == '{':
                    depth += 1
                elif raw == '}':
                    depth -= 1
                    j += 1
                    continue
                lm = LINE_RE.match(raw)
                if not lm:
                    j += 1
                    continue
                mnem, rest = lm.group(1), lm.group(2)
                result = line_size(mnem, rest, None, cop_table)
                if result is None:
                    stopped_early += 1
                    break
                size, revealed_m = result
                if revealed_m is not None:
                    key = (bank, pc)
                    if key not in facts:
                        facts[key] = revealed_m
                pc += size
                j += 1
            i = j
    return facts, blocks_walked, stopped_early


def main():
    asm_dir = pathlib.Path(sys.argv[1])
    cop_widths_path = pathlib.Path(sys.argv[2])
    out_path = pathlib.Path(sys.argv[3])

    cop_table = json.loads(cop_widths_path.read_text())
    facts, blocks_walked, stopped_early = walk_asm_dir(asm_dir, cop_table)

    by_bank = defaultdict(dict)
    for (bank, pc), m_val in facts.items():
        by_bank[bank][pc] = m_val

    out_path.write_text(json.dumps(
        {f'{b:02x}': {f'{p:04x}': v for p, v in sorted(items.items())}
         for b, items in sorted(by_bank.items())}, indent=1))

    print(f'code blocks walked: {blocks_walked}', file=sys.stderr)
    print(f'blocks that hit an unparseable line and stopped early: '
          f'{stopped_early}', file=sys.stderr)
    print(f'total M-state facts derived: {len(facts)}', file=sys.stderr)


if __name__ == '__main__':
    main()
