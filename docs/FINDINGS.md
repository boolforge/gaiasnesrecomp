# Findings

This documents the actual investigation behind this bridge, including
corrected mistakes and ruled-out hypotheses, so nobody has to redo the
same dead ends.

## The two projects, precisely

**Azarem/IOGRetranslation** is a patch/translation project, not a
disassembly. Its `.asm` text is a bespoke DSL (`?BANK`, `?INCLUDE`,
`NAME_BBOOOO { }` for code, `NAME_BBOOOO [ ]` for tables) parsed only
by GaiaLabs' own tooling (`gaia-core`'s `src/rom/rebuild/assembler.ts`,
ported from `GaiaLib/Rom/Rebuild/Assembler.cs`). No relation to
asar/xkas/WLA-DX. Coverage is patch-local: of 636 `?INCLUDE` targets
in this checkout, only 4 resolve to a file inside the repo itself.

**Azarem/gaia-iog-baserom** is the actual whole-ROM structural export:
`us/parts.json` (3,183 entries, each with `start`/`end`/`name`/
`struct`) plus `labels.json`, `groups.json`, `structs.json`,
`scenes.json`, `copdef.json`, `overrides.json`, `fixups.json`,
`rewrites.json`, `stringTypes.json`, `mnemonics*.json`. This bridge is
built against this repo, not IOGRetranslation, because it's complete
rather than patch-local.

**mstan/snesrecomp** decodes the real ROM bytes
(`recompiler/v2/decoder.py`, `program_analysis.py`) and accepts
per-bank `.cfg` boundary hints (`recompiler/v2/cfg_loader.py`) that
seed/correct that decoding. It does not accept and has never accepted
a full text-assembly substitute for the ROM.

## Addressing

`parts.json`'s `start`/`end` are flat `(bank << 16) | offset` integers
in decimal, using Gaia's own canonical low-bank mirror numbering.
Verified directly: `{"start": 98304, ..., "name": "table_018000"}` —
98304 = 0x18000, matching the name's own embedded address exactly.
This is the same canonical-bank form snesrecomp's own HiROM
`canonical_bank = bank & 0x7F` (`recompiler/snes65816.py`) already
produces for a ROM this size, so no translation is needed between the
two, and every bank number in the generated cfg (`$00`-`$14`) is
already in that form.

Illusion of Gaia's ROM header ($31 = HiROM+FastROM, chipset $02 = no
coprocessor) was cross-verified three independent ways: DataCrystal,
an SNES hardware-mapping reference, and GaiaLabs' own
`us/config.json` (`"memoryMode": "Hi"`, `"cpuMode": "Fast"`) — all
agree, and the ROM's own recomputed checksum matches its header
exactly (a clean, unmodified dump).

## Corrected mistakes (kept here on purpose)

- **Assumed Star Ocean was HiROM without checking.** It's LoROM +
  S-DD1 ("ExLoROM"), per its own `SNAGGLETOOTH_FINDINGS.md` and its
  ROM header (map mode $32). Not a HiROM precedent. Corrected once
  verified.
- **Claimed "no HiROM game ships on this framework" based on one
  stale comment in `codegen.py`.** Wrong: DKC and DKC2 are both
  header-verified HiROM ($31) and both ship. Traced why the comment
  survives anyway: fetched the exact `snesrecomp` commit
  (`fe6045c2`) DKC2Recomp's own submodule pins, and the "we don't
  ship a HiROM game yet" comment is present even there. Best
  available read: DKC2's actual code never exercises the specific
  indirect-JML-bank-mirror scenario that comment warns about (no
  `jml_`/`call_far`-style hits found in its generated C), so the
  comment is stale/overly cautious rather than an active blocker —
  not evidence the comment was ever correct for HiROM generally.

## The COP fix (implemented, tested, real gain)

Illusion of Gaia repurposes COP ($02) as a 209-command scripting
dispatch (id byte = the byte after $02). snesrecomp's decoder treats
COP as a fixed 2-byte instruction (correct for hardware, and for
every currently-shipped game, none of which use it this way) — so
every legitimate COP call after the first one in a function gets
mis-decoded, and the analyzer conservatively (and, for this game,
wrongly) marks the whole node `structural_poison`.

Verified id $BF = "PrintWideString" against `copdef.json`, matching
the `COP [BF]` seen immediately before a wide-string literal in
IOGRetranslation's patches — direct confirmation the id-dispatch
model is right, not assumed.

Fix: `recompiler/snes65816.py` gains an optional, opt-in
`_GAME_COP_TABLE` (default `None`) that `decode_insn` consults only
when `set_game_cop_table()` has been called; `program_analysis.py`'s
poison check consults the same table via the id byte (already
captured as `insn.operand`) before flagging a COP site. `tools/
v2_analyze.py` gains `--game-cop-table PATH`, off by default. 81
added lines, 3 files, zero deletions (`patches/
hirom_cop_support.patch`).

The 6/209 commands with `halt: true` (control flow does not fall
through) are excluded from the table on purpose — a wrong guess about
their fall-through behavior would be worse than leaving them at the
pre-existing behavior.

**Regression-tested, not assumed safe:** ran DKC2, Mega Man X2, Mega
Man X3, Star Fox, Star Ocean, Super Mario World, and Zelda: A Link to
the Past through both the untouched baseline and the patched
analyzer, flag *not* passed, using each project's own real cfg. All
seven: deep-equal JSON output, byte for byte semantically identical.

**Measured effect on Illusion of Gaia** (`--all-cfg-roots`
diagnostic, which forces every cataloged function as its own root —
see caveat below):

| | AOT-eligible | LLE-only | total |
|---|---|---|---|
| Before | 519 (22.0%) | 1,839 | 2,358 |
| After  | **1,074 (45.1%)** | 1,310 | 2,384 |

## What "AOT-eligible" ceilings actually look like (measured, not assumed)

Ran the same `--all-cfg-roots` diagnostic, unpatched baseline, against
the two most mature games in this ecosystem, using their own real cfg:

| Game | AOT-eligible | LLE-only | AOT % |
|---|---|---|---|
| Super Mario World (9 months of dedicated work) | 2,122 | 67 | 96.9% |
| Zelda: A Link to the Past | 4,657 | 415 | 91.8% |
| Illusion of Gaia, after the COP fix | 1,074 | 1,310 | 45.1% |

This matters for calibrating expectations: **0% LLE is not the
target, and isn't achievable even for the flagship game** — `docs/
LLE_FIRST_ANALYSIS.md` in snesrecomp states the architecture
explicitly: LLE is a permanent, always-available fallback tier by
design, and AOT is an optional optimization layered on top only where
provably safe. SMW's own floor after nine months is 3.1%, not 0. The
honest target is closing the gap toward that ~90-97% range, not
reaching zero.

(DKC/DKC1 could not be benchmarked the same way — `--all-cfg-roots`
crashes on both, on the unmodified baseline, unrelated to anything in
this bridge: `terminal_jsr at $B3AA6E does not name a direct
three-byte JSR`. Pre-existing behavior of the diagnostic flag itself,
not touched here.)

## BRK poisoning: investigated, not fixed, and here's why

1,050 unique BRK ($00) poison sites remained after the COP fix.
Three hypotheses were tested against real data before concluding none
of them is the dominant cause:

1. **Repetitive padding/data bytes decoding as BRK.** Checked all
   1,050 sites for a run of >=4 identical bytes around the BRK byte:
   only 59 (5.6%) qualify. Real, but minor.
2. **Concentrated in a few buggy functions, cascading to callers.**
   Checked how many distinct cataloged parts contain a BRK site: 953
   distinct parts, and 898 of those (94.2%) contain *exactly one*.
   Not concentrated — ruled out.
3. **An artifact of this bridge's own `end:` boundary computation**
   (i.e. walking a few bytes too far into inter-function padding).
   Checked the distance from every BRK site to its enclosing part's
   declared `end`: only 36/1,028 (3.5%) fall within 5 bytes of it,
   and the rest are spread fairly evenly out to 16+ bytes. Ruled out
   as the dominant cause.

What's left standing, un-disproven, is the explanation snesrecomp's
own source comments already document for *other* specific cases
(`decoder.py`: "AND #$FFFF ... gets sliced into AND #$FF + BRK $0A",
"pointer after JSL APU_UploadBankIP decoded as BRK") — accumulator/
index-width (M/X) mistracking that misaligns the byte stream, landing
on a stray $00 by accident rather than by design. Unlike COP, there
is no single authoritative table (like `copdef.json`) enumerating
these — `ANALYZER_GAPS_INVENTORY.md` describes exactly this class of
problem for SMW's own development: "~40 such gaps [closed over 9
months]... none was anticipated in advance — each one was discovered
by hitting it." The 19 verified M-flag corrections from
`overrides.json` were tried (via `entry_mx_at`) and produced *zero*
change (confirmed: 14/19 addresses are never independently visited as
their own analysis node in this traversal; the other 5 already
matched the analyzer's own inference).

**No fix is included for this.** Forcing one without evidence this
solid would be exactly the shortcut this project set out not to take.
The honest next step is the same one SMW's own history describes:
individually diagnosing specific BRK sites as they're hit, not a
single sweeping correction.

## Pointer-table dispatch validation (investigated further; no cfg change resulted)

Gaia's own data catalogs 14 `&Code`/`&&Code`-typed parts — data tables
whose entries are pointers to code (e.g. `cop_table_008485` +
`cop_table2_008585`, 110 + 99 = 209 entries, one per COP command).
Resolving these directly against the ROM was tried as a way to either
confirm existing `func` coverage or discover legitimately missing
entries.

**A real bug was caught and fixed in the process.** An early pass used
`file_offset = bank*0x8000 + (offset-0x8000)` to map a Gaia address to
a raw ROM byte. That's wrong for a linear HiROM file — verified against
the one byte range with independent ground truth (the SNES header
itself, previously confirmed at raw file offset `0xFFC0` by matching
the exact title string): the wrong formula pointed at 0x7FC0 (garbage
bytes), the correct one — `file_offset = bank*0x10000 + offset` — lands
exactly on `ILLUSION OF GAIA USA`. This bug never touched `bridge.py`
or the shipped cfg/patch (neither reads raw ROM bytes), only a few
exploratory checks earlier in this investigation. Both affected checks
were rerun:
- The BRK "repetitive padding" hypothesis, previously reported as
  5.6% (59/1,050) of sites, is **0% with correct bytes** — even
  weaker support than already reported, not stronger. The other two
  BRK checks (concentration-in-functions, distance-to-declared-end)
  never depended on this formula and are unaffected.
- The cop dispatch tables, re-resolved correctly: **all 209/209**
  entries across both tables land exactly on a cataloged
  `cop_handler_*` part start. Clean, complete confirmation that the
  id-dispatch model is right, and that parts.json already independently
  catalogs every handler these tables reference.

With correct bytes, resolving all 14 tables (1,133 total entries):
389 already match a cataloged `Code` part exactly (sound, redundant
with existing cfg); 185 land inside some *other*, non-Code part
(ambiguous — could be legitimate shared sub-entry points, could be a
per-table encoding difference not yet understood; not added without
more evidence); 16 matched no cataloged part at all. Checked those 16
against the actual ROM bytes before adding anything: all but 2 are
literal `$FF` fill (unused/default table slots, not code), so they
were **not** added as `func` entries — that would have been adding
fabricated boundaries on the strength of a coincidence, exactly what
this project is trying not to do.

**Net result of this pass: no new cfg entries, no AOT/LLE change** —
but real validation of the existing bridge's soundness, a real bug
fixed before it could mislead anything downstream, and 185 legitimately
open questions recorded rather than guessed at.
