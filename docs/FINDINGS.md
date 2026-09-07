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

## Extending the fix to the 6 halt-flagged COP commands

The 6 commands originally excluded (fall-through unknown) turned out
to have a clean answer: GaiaLabs' own `cop.ts` already marks the
position right after a halt-flagged command as a fresh branch target,
i.e. these are genuine terminators, not fall-through continuations.

Extended `decode_insn` to report these 6 specifically as a new
`COP_HALT` mnemonic — a string produced nowhere else in the codebase,
and only by this exact opt-in path — and added it to decoder.py's
existing `_TERMINATORS` set (`{RTS, RTL, RTI, STP, WAI, BRK}`), the
same mechanism that already stops tracing at a real `RTS`. All 209
command widths are now used; none excluded.

Regression-tested the same way as before (DKC2, Mega Man X2, Mega Man
X3, Star Fox, Star Ocean; flag not passed): all five, deep-equal,
unaffected.

| | AOT-eligible | LLE-only | total |
|---|---|---|---|
| Previous | 1,074 (45.1%) | 1,310 | 2,384 |
| Now | **1,212 (50.8%)** | 1,173 | 2,385 |

## This round: no new fix found (reported honestly, not smoothed over)

Two more leads checked for the BRK/M-X problem, both genuine, neither
panned out:

1. **snesrecomp's own tooling for this exact problem** —
   `tools/cfg_override_mode_crosscheck.py` — exists, but is hardcoded
   to cross-reference SMWDisX, an independent, human-maintained Super
   Mario World disassembly, to manually verify claimed M/X states.
   That's the maintainer's own real process for this class of
   ambiguity: cross-check against independent human-vetted ground
   truth, not pure automated inference. There is no equivalent
   independent disassembly of Illusion of Gaia to cross-check against
   the same way, so this tool doesn't transfer as-is.
2. **`us/labels.json`'s `$`-prefixed values** (134 of 402 entries,
   e.g. `"32893": "$1"`) — hoped these might be per-instruction
   width-state hints. Traced to gaia-core's own `DbLabel` type
   (`{location, label}`) and found the code path that would explain
   this file's actual current format is commented out in
   `src/database/root.ts`. Can't respons`ibly claim a meaning for
   this field beyond what's shown — flagged as unresolved rather than
   guessed at.

No cfg or patch change this round. AOT/LLE unchanged at 50.8%/49.2%
(1,212/2,385).

## Actually checking for a missed "developer tool" (asked to verify this directly)

Checked all three real candidates rather than asserting from memory:

1. **gaia-core itself** — `package.json` has no `bin` entry at all;
   `main` points at a compiled library module. It's meant to be
   imported by other TypeScript code, not run from a shell. There is
   no CLI here to have missed.
2. **IOGRetranslation's own `npm run extract` / `npm run rebuild`** —
   these are real, and would be the more authoritative path if
   usable. Read `scripts/seed-init.ts` directly: it constructs
   `new PrismaPg({ connectionString: process.env.DATABASE_URL })` —
   this tooling's actual mode of operation is to read/write GaiaLabs'
   live Postgres/Supabase database. No `DATABASE_URL` (or any
   database credential) has been provided in this project, only a
   GitHub token, so this can't run here. This isn't a workaround
   being avoided — it's the tool's real, documented dependency.
3. **GaiaLabs' C# `GaiaPacker`** — would need a .NET runtime. Checked
   directly rather than assuming: `dotnet-sdk-8.0` is listed by
   `apt-cache` but every package file 404s when actually fetched from
   the reachable Ubuntu mirrors. Not installable in this environment,
   confirmed by a real failed install attempt, not a guess.

If whoever runs this bridge next has real `DATABASE_URL` credentials
for GaiaLabs' own database, `npm run extract` in an IOGRetranslation
checkout is very likely a better foundation than this repo's current
`parts.json`-only approach — that's a genuine, specific, actionable
next step, not a hedge.

Also checked `us/rewrites.json` (39 address-to-address entries, never
previously examined) against all current BRK poison sites: only 1/39
falls within even a loose 8-byte window of one. Not a meaningful
correlation — doesn't explain the BRK problem either.

## The breakthrough: actually running GaiaPacker (found and fixed a real bug in it too)

Got `GaiaPacker.dll` (from the official `baserom_toolkit_v1.1w`
GitHub release) running under a Linux-installed .NET 8 runtime
(`dotnet-runtime-8.0` via `apt`, after an earlier full-SDK attempt had
failed on package-mirror 404s — the runtime-only package pulled fine).
`dotnet GaiaPacker.dll --unpack .` crashed twice before working:

1. Passing a bare directory (`.`) as the project path hits a
   *different* code branch in `ProjectRoot.Load()` than passing the
   actual `project.json` file does, and that branch never sets
   `SystemPath` at all (confirmed by reading `ProjectRoot.cs` and
   `DbRoot.cs` directly from Azarem/GaiaLabs) -- a real bug in the
   tool itself, not a missing file. Fixed by invoking it with the
   file path explicitly: `dotnet GaiaPacker.dll --unpack ./project.json`.
2. The release's `db/us/` folder has no `opCodes.json` (only `db/jp/`
   does) -- copied that one over, which is safe: CPU opcodes don't
   vary by ROM region, verified by inspecting its content (a generic
   256-entry 65816 mnemonic/size/mode table).

Once running, it unpacked the **real, complete, human-authored
disassembly**: 806 `.asm` files, organized by game area, with names
like `dm47_remus.asm` (a named NPC) rather than bare addresses --
categorically more complete than IOGRetranslation's 133 patch-only
files this bridge started from.

## Deriving real M-state facts from the real disassembly (net win)

Manually traced one already-known BRK poison site (bank $09, offset
$B6B6) into this new corpus and found the actual cause directly:
`asm/unused/actor_09AA6E.asm` (yes -- unused/dead code) shows `ADC
#$0002` at that exact point -- a 16-bit (M=0) immediate. Counting
bytes confirms $B6B6 is the immediate's own high byte ($00), which
`v2_analyze.py` was mis-decoding as a fresh BRK opcode because it had
inferred 8-bit (M=1) there instead. Exactly the failure mode
`decoder.py`'s own comments already describe elsewhere -- now directly
confirmed against real, human-verified ground truth instead of
inferred from raw bytes.

Wrote `bridge/derive_mx_facts.py`: walks every code block in the real
`asm/` corpus from its own labeled address, sizing each instruction
from its literal operand syntax (Gaia's text already writes `#$XX`
vs `#$XXXX` -- 2 vs 4 hex digits -- so the true M state is a lexical
fact already decided by the disassembler, not something that needs
re-simulating REP/SEP for). Stops a block's walk the moment a line's
addressing mode isn't confidently sized, rather than guess past it.

Result: 8,358 code blocks walked, 7,216 M-state facts derived, 544
blocks stopped early (deliberately, not silently). Verified against
the manually-traced example above (exact match) and spot-checked
independently before use. Zero address overlap with the 19 hand-
verified `overrides.json` facts (different addresses entirely; the
hand-verified ones win on the rare occasions of a conflict).

Regression-tested the same way as every previous change (now against
all seven other games this project has ROMs and cfg for: DKC2, Mega
Man X2, Mega Man X3, Star Fox, Star Ocean, Super Mario World, Zelda:
A Link to the Past) -- all seven, byte-identical, confirmed via deep
JSON equality.

| | AOT-eligible | LLE-only | total |
|---|---|---|---|
| Previous | 1,212 (50.8%) | 1,173 | 2,385 |
| Now | **1,360 (55.7%)** | 1,083 | 2,443 |

## Pointed to the real answer: `docs/code/bank00/cop-dispatch.md`

This file (added upstream to `gaia-iog-baserom` since this bridge's
last check) states outright what every COP handler's entry register
state is: **m=0, x=0** for all 209 handlers -- documented directly
from the dispatcher's own `REP #$20` and the actor-engine calling
convention, not inferred. This directly corrects the X=1 assumption
this project had been using since the very first COP fix (it was
never verified, always flagged as an assumption -- it was wrong).

Injected `entry_mx_at <addr> 0 0` at all 209 cop_handler entry points.
Regression-checked against DKC2, SMW, and Zelda: A Link to the Past
again: unaffected.

| | AOT-eligible | LLE-only | total |
|---|---|---|---|
| Previous | 1,360 (55.7%) | 1,083 | 2,443 |
| Now | **1,554 (61.7%)** | 965 | 2,519 |

Note: `gaia-iog-baserom` removed `us/parts.json` upstream in this same
update (replaced by `blocks.json` + a much smaller `names.json`).
This bridge's cfg was already generated before the removal, so it's
unaffected for now, but `bridge/bridge.py` needs updating to read
`blocks.json` directly next time it's regenerated from a fresh clone.
