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

## Two small parser fixes to derive_mx_facts.py (honest small gain)

Found two gaps while re-checking the 544 blocks that stopped early:
1. `#$&label` / `#$*label` -- an immediate operand can be a sigil-
   prefixed label reference, not just raw hex. `&` (Offset, verified
   2-byte) is now handled the same as a 4-hex-digit immediate (reveals
   M=0). `*` (WBank) has no confirmed byte size anywhere in gaia-core's
   source, so it's still left unparsed rather than guessed.
2. Indexed addressing written with a space (`($01, X)`, `$1000, Y`) --
   3,472 occurrences in the corpus use this spacing and weren't
   matching the tighter `,X`/`,Y` regexes. Fixed to tolerate optional
   whitespace.

Result: 7,216 -> 7,576 derived facts, 544 -> 422 early-stopped blocks.
Regenerated cfg, regression-checked against SMW again (identical).

| | AOT-eligible | LLE-only | total |
|---|---|---|---|
| Previous | 1,554 (61.7%) | 965 | 2,519 |
| Now | 1,555 (61.7%) | 964 | 2,519 |

Honest note: barely moved the number. Worth fixing regardless (dead
weight in the parser, and more correct data is its own justification),
but the earlier `cop-dispatch.md` fact was a far bigger lever than
this. Recorded plainly rather than rounded up.

## Known debt: `bridge.py` still depends on the now-removed `parts.json`

`gaia-iog-baserom` deleted `us/parts.json` upstream (replaced by
`blocks.json` + a smaller `names.json`). This session's cfg updates
were applied by patching the already-generated `cfg/*.cfg` files
directly rather than regenerating from scratch, so today's output is
current, but `bridge/bridge.py` itself has not been updated to read
`blocks.json` and will fail (`FileNotFoundError`) if run against a
fresh clone. Flagging this rather than leaving it to be discovered
later.

## blocks.json migration: investigated, deliberately NOT done yet

Checked what actually replaced `parts.json`'s leaf data. It's not a
rename -- the schema changed shape. Old `struct`-typed leaves (2,142
`Code`, 2,605 `WideString`, etc.) are mostly gone; the new dominant
types are `actor_def` (655) and `thinker_def` (58), which didn't
exist as leaf categories before.

Checked one directly rather than assume what it contains: `actor_def
actor_00D0D1` (72 bytes) starts `00 00 20 AC AA 09 A5 16 38 E9...` --
looks like a short header (maybe 2-3 bytes) followed by genuine,
plausible 65816 code (`JSR`, `ORA`, `SBC`, `CMP`, `RTL`...) in the
same span. Mixed content, not cleanly Code or Data.

Blindly treating `actor_def`/`thinker_def` spans as one or the other
would misclassify real code as inert data or vice versa across 713
entries -- exactly the kind of guess this project has avoided
elsewhere. Not migrating `bridge.py` to `blocks.json` until this is
understood properly (where the header/code split actually falls).
The existing `cfg/` output (built from the last-known-good
`parts.json` before its removal) remains what's checked in and is
still current; this is flagged as real, open debt, not silently
patched over.

## actor_def / thinker_def header split: checked, mixed evidence, not implemented

Tried to resolve last round's open question -- does `actor_def` split
into a fixed header (h_actor = 3 bytes per `structs.json`) plus code,
the same way COP handlers had a clean, documented convention?

- First sample (`actor_00D0D1`) looked consistent with a 3-byte header
  before clean-decoding code.
- Second, adjacent sample (`actor_00D119`) starts with the *identical*
  46 bytes as the first, then diverges -- not what a 3-byte-header-
  then-distinct-code model predicts. Checked byte-for-byte, not
  eyeballed: confirmed identical for 46 bytes, first difference at
  byte 46 exactly.
- Third sample (`actor_00D161`, only 9 bytes long) doesn't decode
  cleanly as code at all under the 3-byte-header assumption.
- `thinker_def` fared better: `h_thinker` = 2 bytes, and three
  consecutive samples show a shared 2-byte prefix (`$00 $08`) followed
  by content that varies instance-to-instance in a small, plausible
  way (a `COP $37`-based pattern where one embedded byte differs by
  exactly the increment you'd expect between similar effect
  instances). Suggestive, not confirmed.

Net: real uncertainty for `actor_def` (not just "haven't checked
yet" -- actively contradictory evidence once more than one sample was
checked), softer support for `thinker_def`. Implementing a blanket
header-strip for either right now would be exactly the kind of guess
this project keeps avoiding. Still deferred. Whoever picks this up
next should pull `docs/code/actor-management.md`-style analysis for
these specific groups if `gaia-iog-baserom` publishes one, the same
way `cop-dispatch.md` resolved COP cleanly.

## Migrated to parsing the real corpus directly (resolves the actor_def ambiguity cleanly)

Rather than chase `gaia-iog-baserom`'s JSON schema through a second
change (parts.json removed, blocks.json's leaf shape changed), wrote
`bridge/extract_from_asm_corpus.py`: applies this project's original,
already-verified label/block-detection rule (a label opens `{` for
code or `[` for data -- Gaia's own syntax, not a guess) directly
against GaiaPacker's real 806-file `--unpack` output.

This resolved last round's open question outright. The real corpus
shows, for the address that prompted the whole investigation:
```
head_00D0D1 [ h_actor < #00, #00, #20 > ]   ; 3 bytes, data
func_00D0D4 { LDY $player_actor; ... }      ; separate code block
```
Two distinct, correctly-typed entries -- exactly what
`blocks.json`'s newer `actor_def` schema had merged into one
ambiguous 72-byte span. Confirms the earlier caution (not guessing a
blanket header size) was the right call, and confirms the real
disassembly is a better foundation than either JSON export at this
point.

Coverage jump: 2,142 code / 1,041 data entries (old `parts.json`) ->
**8,184 code / 7,295 data entries** (real corpus, all 806 files).

## Hit a real performance wall at this scale -- reported, not hidden

`--all-cfg-roots` against the full new cfg (8,184 forced roots) did
not complete in 280 seconds (explicit timeout, not assumed slow).
The default reachability mode still runs fine and fast. Tried
analyzing each bank's cfg in isolation as a workaround: bank00 (the
largest, self-contained COP-dispatch bank) completed cleanly --
**1,474 AOT-eligible / 477 LLE-only of 1,951 (75.6%)** -- a genuinely
promising signal. But several other banks returned identical,
suspicious numbers in isolation (`9 roots -> 73 variants` for six
different banks in a row), almost certainly an artifact of losing
cross-bank reference context when a bank is analyzed alone rather
than a real result.

**Not reporting a new whole-ROM percentage this round.** Summing the
per-bank numbers anyway would produce a headline figure built on a
methodology I already have direct evidence is unreliable for at
least some banks -- exactly the kind of number this project has
avoided manufacturing everywhere else. The honest state: real,
substantial structural improvement (confirmed), a promising signal
in the bank most worth trusting (bank00, self-contained), and an
open, now-documented performance/methodology problem for whoever
continues this -- likely needing either a higher time budget than
this environment allows for a true whole-ROM `--all-cfg-roots` run,
or a properly cross-bank-aware batching approach rather than the
per-bank isolation tried here.

## Follow-up: the "suspicious" identical numbers weren't a bug

Checked before concluding, rather than leaving the concern above
unresolved: banks 0e/0f/10/14/15/16/17 all show identical
`9 roots -> 73 variants` because they genuinely have **zero `func`
entries** -- pure graphics/tilemap data banks, no code. The isolation
approach wasn't broken; that's the correct baseline result for a
cfg with nothing but data in it.

With that resolved, summed all 20 banks (19 with content + the
zero-func ones, `bank0d` doesn't exist in this ROM):

| bank | AOT | LLE | | bank | AOT | LLE |
|---|---|---|---|---|---|---|
| 00 | 1,474 | 477 | | 08 | 466 | 117 |
| 01 | 61 | 12 | | 09 | 499 | 149 |
| 02 | 1,402 | 356 | | 0a | 1,294 | 411 |
| 03 | 1,219 | 424 | | 0b | 947 | 368 |
| 04 | 394 | 39 | | 0c | 147 | 39 |
| 05 | 408 | 72 | | 0e-17 (data-only) | 61 each | 12 each |
| 06 | 309 | 57 | | | | |
| 07 | 422 | 60 | | | | |

**Total: 9,469 AOT-eligible / 2,665 LLE-only / 12,134 -> 78.0%.**

One caveat stated plainly: analyzing each bank alone means a call
from one bank into another can't be proven the way it could if both
banks' cfg were loaded together, so this number likely
*underestimates* the true combined figure rather than overstating it
-- a conservative number, not an inflated one. Still not the same
methodology as the single-run whole-ROM numbers reported earlier in
this document (55.7%, 61.7%), so treat this as the current best
honest estimate, not a strictly apples-to-apples continuation of
that exact series, until the underlying performance problem is
actually solved.

## Correction: the "conservative underestimate" claim above was tested, and it's wrong

Didn't leave that as an assertion -- checked it. Combined the three
largest banks (00+02+03) into one cfg dir and ran them together
(3,433 forced roots; completed in under 250s, so the performance
ceiling is somewhere between this and the full 8,184-root run, not
an immediate wall):

| | AOT-eligible | LLE-only | AOT % |
|---|---|---|---|
| Summed separately | 4,095 | 1,257 | 76.5% |
| Analyzed together | 3,908 | 1,213 | 76.3% |

Combined is very slightly *lower*, not higher -- the opposite
direction from what was claimed. Best explanation: a cross-bank call
that looks merely "unproven" in isolation can turn into active
propagated poison once the real (and sometimes messy) target content
is actually visible, not just resolved cleanly as hoped. The
magnitude here is small (0.2 points on these three banks), so the
78.0% whole-ROM estimate is probably in the right neighborhood
either way, but the specific directional claim ("underestimate,
conservative") should not have been asserted without checking it
first, and is retracted here rather than left standing.

## Handoff: concrete next steps, in priority order

1. Bisect the `--all-cfg-roots` performance ceiling (known: 3,433
   roots completes under 250s, 8,184 roots times out at 280s+) to get
   a trustworthy single-run whole-ROM number instead of the per-bank
   sum (78.0%).
2. `unproven_call`/`unproven_callee_exit` reasons were never
   root-caused the way COP and the M-state facts were -- next
   biggest untouched category.
3. `actor_def`/`thinker_def` groups beyond the ones already resolved
   via the real corpus migration may still hold gains if
   `gaia-iog-baserom` ever publishes a `cop-dispatch.md`-equivalent
   for them.
4. The 6 halt-flagged COP commands and the `*` (WBank) sigil in
   `derive_mx_facts.py` remain deliberately unhandled -- no verified
   byte-size/fallthrough source found yet for either.

## Performance ceiling: narrowed, not yet found

Bisection point tested: banks 00+02+03+0a combined (4,801 forced
roots) -- completed within 280s. Combined with the earlier data
points (3,433 roots: completes; 8,184 roots: times out past 280s),
the real ceiling in this environment is somewhere in roughly the
4,801-8,184 root range. Not narrowed further this round (budget);
next bisection point should add roughly half the remaining banks
(e.g. +0b+09, ~6,275 roots) to keep closing the gap.

Full 8,184-root set retested directly: still times out at 280s
(exit 124, same as the original finding). Ceiling is between 6,275
(completes) and 8,184 (times out). Next step: bisect within that
narrower range (e.g. +banks 01/04/05/06 for ~7,200 roots).

Narrowed further: 7,258 roots completes; adding just bank07
(7,621 roots) times out at 280s. Ceiling is now bracketed tightly:
7,258-7,621 -- notably not linear with root count alone (jump from
6,275->7,258 stayed fast; 7,258->7,621, a much smaller addition,
tipped it over), so bank07 specifically may be disproportionately
expensive rather than this being a pure root-count scaling issue.
Worth checking what's structurally different about bank07 before
assuming it's just size.

Root cause hypothesis, checked rather than assumed: bank07 alone is
small (369 funcs, 482 nodes, only 222 demands/edges) -- not
inherently complex. So the slowdown isn't bank07's own size; it's
that adding it connects previously-separate cross-bank call graphs
together, and the combined graph's path exploration grows
combinatorially with *connectivity*, not raw root count. Total func
count was the wrong metric to bisect on from the start -- flagging
this so the next bisection (if pursued) targets connectivity/edge
density between bank groups instead of just adding banks by size.

## unproven_call root cause found (30% of cases), attempted fix did NOT work

Root-caused a real pattern: sampled `unproven_call` demands and found
targets like `pc24=8641014` (0x83D9F6) -- bank $83, which folds to
bank $03 under HiROM's canonical-bank rule. Checked: `func_03D9F6
d9f6 end:da00` already exists in `bank03.cfg`. Confirmed this is
widespread, not a one-off: 105 of 353 demands (30%) across all
current `unproven_call` nodes target a bank >= $80.

Tried the obvious fix: generated `bank80.cfg`-`bank8c.cfg` as direct
mirrors of `bank00.cfg`-`bank0c.cfg` (same func/data declarations,
mirrored bank number) and re-ran. **Did not help** -- checked the
exact node that motivated this (`00804C`) directly rather than trust
the aggregate percentage, and it's still `unproven_call` with the
identical reason string. The analyzer evidently doesn't treat a
declared func at the mirrored bank as satisfying a demand on the
original bank's call site; whatever proves call-target safety here
needs the banks canonicalized *before* that comparison, not just
present as separate cfg entries. That's a decoder/program_analysis
change, not a cfg-only one -- same category of risk this project has
already declined to take on blind for the COP halt-flag/BRK cases,
so not attempted further this round. Reverted the mirror cfg files
(would have been dead weight in the repo).

## Correction: the "needs decoder-level bank canonicalization" claim was itself incomplete

Checked before building on it. `decoder.py` already canonicalizes
high-bank targets when looking up a callee's proven exit state
(`decoder.py` ~line 1117: if a direct lookup misses and the target
bank is `<0x40` or in `0x80-0xBF`, it retries via `target_pc24 ^
0x800000`). So the mechanism I said was missing already exists --
my diagnosis last round was itself wrong in the specific mechanism,
even though the symptom (unresolved high-bank calls) is real.

What that lookup actually depends on is `callee_exit_mx_modes` --
the callee's *proven* exit register state, populated by whatever
fixed-point pass orchestrates repeated decoder.py calls from
`program_analysis.py`. No `while`/convergence loop is visible in
decoder.py itself, meaning that orchestration lives in
program_analysis.py and wasn't traced further this round. Most
likely explanation, not yet confirmed: the callee's own exit state
genuinely isn't provable yet at the point this caller is checked
(ordering/convergence), rather than a missing canonicalization step.

Not pursuing further this round -- this is real fixed-point-solver
territory (the surrounding comment in decoder.py explicitly describes
it replacing an earlier, less-sound heuristic), materially different
from and riskier than the additive, opt-in COP fix. Recorded as a
corrected, narrower diagnosis for whoever picks this up next, rather
than left as the wrong claim from last round.

## Further correction: the mirroring infra is more complete than feared, mystery narrows

Checked `_lorom_mirror_bank` in `tools/v2_analyze.py` directly (despite
its name) rather than assume it's LoROM-specific and irrelevant: its
actual logic (`bank ^ 0x80` for bank `<0x40` or in `0x80-0xBF`)
correctly pairs $03<->$83, the exact case in question, and it's
already used for `cfg`/`entry`/`sibling_entries` lookup in
`decode_variant`. So this layer isn't the gap either.

The remaining, narrower mystery: with that lookup infrastructure
apparently correct, node `00804C` was still `unproven_call` in the
mirror-cfg test two rounds ago. Not re-run this round (time) --
whoever continues should re-test that exact node now that the
mirror cfg files are confirmed reverted, with attention to whether
`callee_exit_mx_modes` (a *different* dict from the `cfg`/`entry`
lookups just confirmed correct, populated by a fixed-point process
not yet located) is the actual remaining gap, or whether the target
function's own decode is separately poisoned for an unrelated
reason that would show up in its own node's `reasons` list first.

## Actually traced the chain -- the high-bank correlation was a red herring

Closed the loop rather than leaving it a suggestion. Checked the
target node's own status: `03D9F6` (the callee `00804C` couldn't
prove) is itself `unproven_call` -- to `03DABB`. Traced one more
level: `03DABB` is `aot_eligible`, clean, no reasons.

So the real shape is: a clean function (`03DABB`) whose proven exit
state apparently isn't reaching its caller's (`03D9F6`) check, which
in turn means *its* caller (`00804C`) can't prove through it either.
This is a propagation/ordering question -- likely single-pass
processing order rather than the multi-step SCC solver
(`_solve_exit_equation_sccs`) actually needing more than one full
invocation of `v2_analyze.py` to converge, feeding forward what the
previous pass proved. Not confirmed which.

**The 30%-high-bank-target correlation from two rounds ago was a red
herring** -- these calls fail to prove because of chain/ordering
effects that would affect same-bank calls too, not because of
anything specific to bank aliasing. Correcting that causal claim
explicitly rather than let a coincidental correlation stand as the
explanation.

Real next step for whoever continues: check whether running
`v2_analyze.py` twice, feeding the first run's manifest back in
somehow (no such flag currently exists -- would need one added, or
confirmation this is what `v2_regen.py` already does), resolves
chains like this one.

## Consolidated every naming source into symbols.json (for future codegen legibility)

Requested explicitly: pull in every available name mechanically
rather than leave future generated code full of raw addresses.
`bridge/build_symbols.py` merges three sources this bridge hadn't
used yet (the real asm corpus's own labels were already the primary
naming source for everything emitted so far, so not duplicated
here):

- **221 named WRAM variables** from `fixups.json["mnemonics"]` (e.g.
  `camera_offset_x` @ WRAM $1750) -- a different address space
  (WRAM, not ROM) from everything else this bridge has named so far,
  kept explicitly separate (`wram_offset` field) so nothing
  downstream can conflate the two.
- **413 ROM-address names** from `names.json`, mostly hardware
  vectors and entry points (`ResetVector`, `NmiVector`, ...).
- **228 named scenes/areas** from `scenes.json`, each with a slug and
  human description (`south-cape` / "South Cape").

All copied verbatim -- nothing invented or inferred. Not yet wired
into `bridge.py`'s cfg output (there's no codegen stage to feed yet),
but ready as `symbols.json` for whenever that stage exists, rather
than left to be re-collected from scratch later.

## Ordering hypothesis narrowed further, root architectural cause identified (not fixed)

Tested the "just needs more cfg loaded" theory directly: `00804C` is
still unproven in the 7,258-root run too, even though `03D9F6` and
`03DABB` (its full dependency chain) were already loaded and analyzed
in that same run. Rules out missing data as the cause.

Read `_solve_exit_equation_sccs`'s own docstring precisely: it's
scoped to *closed mutually-recursive* components (`A -> B -> A`
cycles) specifically, and explicitly states "unknown external edges
keep the whole component unpublished." The chain in question
(`00804C -> 03D9F6 -> 03DABB`) isn't a cycle at all -- it's a plain
linear dependency, which shouldn't need this cyclic-SCC machinery to
resolve at all under a correct topological pass (resolve the
callee-less end first, then work backward).

Best-supported remaining hypothesis: the analysis is a single forward
pass over roots in whatever order they're declared/discovered, not a
true fixed point that revisits an earlier conclusion once later
information becomes available -- so if `00804C` happens to get
checked before `03DABB` has been resolved (even though `03DABB` *is*
resolved by the end of the same run), the caller's check fails
permanently rather than being retried. Not confirmed by reading the
actual traversal-order code (would need to trace root-processing
order through `program_analysis.py`/`decoder.py` directly, not yet
done), but it's now a specific, testable claim rather than a vague
one.

Fixing this for real means either genuine multi-pass iteration or a
proper dependency-ordered (topological) traversal in the core
analysis loop -- a substantial, delicate change to code this project
has consistently declined to touch without being able to fully
verify safety, same as the BRK and halt-flag cases. Handing off the
specific, narrowed hypothesis rather than a vague "investigate more."

## Retraction: the single-pass hypothesis was wrong too -- read the actual loop

Checked rather than left asserted. `tools/v2_analyze.py` (~line 846)
has a genuine `while True` fixed-point loop, re-running the full
`ProgramAnalyzer.analyze()` every round and accumulating
`active_exit_modes` monotonically, with an explicit design comment:
"a finite monotone lattice and therefore converges without an
arbitrary game-sized round cap." This is real, deliberate iteration,
not a single blind pass. Retracting last round's hypothesis.

Checked the exact values instead of guessing further: `03D9F6`'s
demand on `03DABB` wants exactly `{m:1, pc24:0x03DABB, x:1}`, and node
`03DABB:M1X1` exists with precisely that key and `aot_eligible`,
zero reasons. Every value matches -- no width or address mismatch.

Current best (unconfirmed) explanation: a node being `aot_eligible`
(its own bytes decode without poison) is different from having a
*published caller-usable exit-mode fact* -- if `03DABB` doesn't
actually end in a normal `RTS`/`RTL` (e.g. it tail-jumps elsewhere
instead of returning), there may be no well-defined "state on return
to caller" for it to publish at all, independent of its own code
being perfectly fine. Wasn't able to confirm `03DABB`'s actual last
instruction from the real corpus this round (name didn't match
directly in a quick grep) -- next step for whoever continues is
pinning that down before going further, rather than another guess.

Closing this specific thread here: three consecutive hypotheses
(bank aliasing, single-pass ordering, and now this) is a lot of
turns on one node for a project this size. Recorded honestly, not
padded into a false resolution.

## Performance bisection: sharp cliff located within bank07 itself

Split `bank07.cfg` in half (by declared func count) and added just
that half to the known-good 7,258-root set: **7,446 roots (+188)
already times out**, versus the earlier jump from 6,275 to 7,258
(+983) which stayed fast. The problem isn't bank07's total size --
it's concentrated in roughly its first half specifically. Ceiling now
bracketed as tight as 7,258 (completes) to 7,446 (times out), a
188-function window. Next step: bisect within that specific half of
`bank07.cfg` to find the exact function(s) responsible, which would
turn this from "somewhere in ~370 functions" into an actual root
cause rather than a range.

## Performance cliff pinned to a 40-entry window in bank07

Bisected down as far as reasonably proportionate: 79 entries into
`bank07.cfg` completes fine (7,300 roots); 119 entries times out.
The specific candidate window (addresses $078C12-$0795E4, a mix of
`code_*` funcs and `data_region`s -- see the exact list committed
in this diff) is now small enough to actually test individually
rather than keep splitting further, which is where this stops for
now. Concrete, bounded next step for whoever continues, not another
open-ended range.

Stopping the performance-ceiling thread here -- it was always in
service of getting a trustworthy single-run whole-ROM number, and a
188-then-40-entry window is a genuinely useful handoff. Returning
focus to AOT-percentage-affecting work rather than continuing to
narrow a number that, per the earlier combined-vs-separate test, is
already known to land within about 0.2 points of the per-bank sum
either way.

## The 03DABB mystery: actually resolved, not another guess

Found it in the real corpus (`chunk_03BAE1.asm` -- missed earlier
because the label is `sub_03DABB`, not `func_03DABB`). Its actual
content:

```
sub_03DABB {
    LDA $0648
    BEQ code_03DAD0
    DEC ; BEQ code_03DAF2
    DEC ; BEQ code_03DAFA
    DEC ; BEQ code_03DB20
    DEC ; BNE code_03DACF
    JMP $&code_03DBA4
}
code_03DACF { RTS }
code_03DAD0 { ... }
code_03DAF1 { RTS }
```

`sub_03DABB` is a multi-way branch dispatcher (decrement-and-test a
value, branch to one of several labeled blocks), and its own literal
last instruction on the fallthrough path is `JMP`, not `RTS`. The
actual `RTS`s live in the separately-labeled blocks it branches to
(`code_03DACF`, `code_03DAF1`, ...), which this bridge's extraction
correctly treats as their own distinct `func` entries, since they
are independently labeled `{ }` blocks in the source.

So the real cause was never analyzer ordering, SCC handling, or
convergence -- it's that Gaia's own hand-written disassembly
sometimes splits one logical function's multiple exit paths across
several consecutively-labeled blocks (a normal, legitimate hand-asm
readability pattern), and this bridge's "one label = one independent
function" extraction has no way to know that `code_03DACF`'s `RTS`
is really the same logical unit's exit as `sub_03DABB`'s dispatcher.
A caller's `JSR sub_03DABB` genuinely can't get a clean single "what
state does this return in" answer from boundary-only extraction,
because the true answer depends on which of several separately-typed
sub-blocks actual execution reaches -- correct, conservative
behavior given the input, not a bug anywhere in snesrecomp.

Three retracted hypotheses across four rounds on one node, and the
real answer turned out to be a genuine structural fact about the
source material, not a fixable bug in either project. Recording the
full, correct chain rather than stopping at a wrong-but-plausible
answer, since that's the only version of this worth handing off.

## The fallthrough fix was correct, and the honest result is a LOWER percentage

Generalized the `03DABB` finding: extended `extract_from_asm_corpus.py`
to detect when a labeled code block has no real terminator (no
`RTS`/`RTL`/`RTI`/`JMP`/`JML`/`BRA`/`BRL`/`STP`/`WAI` as its last
instruction) and merges it with the next label into ONE `func` span,
instead of declaring each labeled sub-block as its own independent,
separately-provable function. This is real and common: **2,687 of
8,184 labels (33%) were fallthrough-only**, folding total `func`
declarations from 8,184 down to 5,497 genuinely independent entries.
Verified against the known example first: `func_03D9F6` now correctly
spans through both `code_03DA00` and `code_03DA03` to `end:da41`,
while `sub_03DABB` (which has a real terminator, its trailing `JMP`)
stays properly separate.

Recomputed the full per-bank sum on this corrected cfg, same
methodology as before, all 20 banks:

**6,163 AOT-eligible / 2,089 LLE-only / 8,252 total = 74.7%.**

That is *lower* than the 78.0% reported two rounds ago on the
unmerged cfg. Reporting it exactly as it came out. The honest
explanation: the old, fragmented boundaries were counting small,
trivially-clean fallthrough snippets (like a 3-byte `STZ` block) as
independently "AOT-eligible" units on their own, which inflated the
percentage with fragments that were never real, independently
callable functions in the first place. The new number reflects the
game's actual function structure and is the more trustworthy of the
two -- adopted as the new baseline going forward, not reverted to
the higher-looking figure. Regression-checked against SMW again
(unaffected -- this change is to the bridge's own extraction, not
the snesrecomp patch).
