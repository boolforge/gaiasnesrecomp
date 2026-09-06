# gaiasnesrecomp

> _This is the bridge layer between two independent projects, not a
> fork of either: [Azarem/gaia-iog-baserom](https://github.com/Azarem/gaia-iog-baserom)
> (GaiaLabs' Illusion of Gaia disassembly/translation toolchain) and
> [mstan/snesrecomp](https://github.com/mstan/snesrecomp) (the SNES
> static recompilation framework used by
> [SuperMarioWorldRecomp](https://github.com/mstan/SuperMarioWorldRecomp),
> [ZeldaAlttPSNESRecomp](https://github.com/mstan/ZeldaAlttPSNESRecomp),
> [DKC2Recomp](https://github.com/mstan/DKC2Recomp), and others).
> Everything here is analysis and glue code. **There is no playable
> build yet** — see Status below before expecting one._

Illusion of Gaia (SNES) is HiROM, uses no coprocessor, and — unusually
for anything on this framework so far — repurposes the 65816's `COP`
instruction as a 209-command scripting dispatch. None of the games
currently on snesrecomp do that. This repo exists to feed snesrecomp
real, sourced structural knowledge about this specific game instead of
letting its analyzer guess.

## What this is (and isn't)

- **Is:** a bridge script that turns GaiaLabs' own whole-ROM export
  (`gaia-iog-baserom`) into snesrecomp's native `.cfg` boundary-hint
  format, plus a small, opt-in patch to snesrecomp's decoder that
  teaches it this game's COP dispatch table.
- **Isn't:** a disassembler, a decompiler, or a fork of either
  upstream project. It reads GaiaLabs' already-published data and
  writes files in snesrecomp's already-documented cfg grammar. No ROM
  bytes, game text, or generated C are redistributed from this repo.
  `mx_facts.json` and `cfg/*.cfg` are derived facts (byte sizes,
  addresses, boolean width flags) about the ROM's structure, not the
  ROM's own content.
- **Isn't (yet):** a working port. No runtime, no generated C game
  logic beyond what snesrecomp's own analyzer produces from the cfg,
  no build. See `docs/FINDINGS.md` for exactly how far the analysis
  actually gets and why.

## Repo layout

```
bridge/bridge.py        Single entry point: baserom JSON -> cfg/ + cop_widths.json
patches/                Opt-in decoder patch for snesrecomp (see below)
cfg/                    Generated output of bridge.py, checked in for convenience
cop_widths.json         Generated output of bridge.py, checked in for convenience
docs/FINDINGS.md         The actual investigation: what was verified, what was
                         ruled out, and the corrected mistakes along the way
```

## Requirements

- Python 3.9+, no third-party packages.
- A checkout of [Azarem/gaia-iog-baserom](https://github.com/Azarem/gaia-iog-baserom)
  (for regenerating `cfg/` and `cop_widths.json` from source — the
  checked-in copies already reflect it as of this writing).
- A checkout of [mstan/snesrecomp](https://github.com/mstan/snesrecomp)
  (to apply `patches/hirom_cop_support.patch` against) and your own
  legally-dumped Illusion of Gaia ROM, to actually run the analysis.
  **No ROM is included or required by this repo on its own.**

## Usage

```bash
# 1. Regenerate cfg/ and cop_widths.json from a baserom checkout
#    (optional -- the repo already ships current output)
python bridge/bridge.py \
  --baserom /path/to/gaia-iog-baserom/us \
  --out-cfg cfg \
  --out-cop-widths cop_widths.json

# 2. Apply the decoder patch to your own snesrecomp checkout
cd /path/to/snesrecomp
git apply /path/to/gaiasnesrecomp/patches/hirom_cop_support.patch

# 3. Run snesrecomp's real analyzer against your own ROM
python tools/v2_analyze.py \
  --rom "Illusion of Gaia (USA).sfc" \
  --cfg-dir /path/to/gaiasnesrecomp/cfg \
  --manifest manifest.json \
  --game-cop-table /path/to/gaiasnesrecomp/cop_widths.json
```

Step 2's patch is inert for every other game on this framework unless
`--game-cop-table` is explicitly passed — see `docs/FINDINGS.md` for
the regression tests this claim is based on, not just an assertion.

## Status

Analysis/bridge stage. With the COP-dispatch fix and the M-state
facts derived from GaiaPacker's own real disassembly output (see
`docs/FINDINGS.md`), **55.7% of Illusion of Gaia's cataloged
functions classify as cleanly statically-recompilable (AOT-eligible)**
(1,360/2,443), up from 22.0% at the start of this project — real,
measured, regression-tested against seven other games on the
framework each time, not a projection.

No runtime, no generated-and-verified C game logic, and no build
exist yet. That is the natural next stage, following the same pattern
as the per-game repos linked above, once analysis coverage is
further along.

## Licensing note

This bridge depends on two upstream projects under different licenses
— `gaia-iog-baserom` (GPL-3.0) and `snesrecomp` (PolyForm
Noncommercial 1.0.0) — which aren't obviously compatible with each
other for a combined redistributed work (GPL-3.0 doesn't permit
adding a noncommercial restriction on top of it; PolyForm-NC forbids
commercial use outright). This repo doesn't attempt to resolve that
by picking a license unilaterally. Treat this code as intended for
the same personal/research use both upstream projects are already
used for until whoever owns this repo (and ideally both upstream
maintainers) sorts out the actual answer.

The ROM is never included here, and never will be — same policy as
every project linked above.
