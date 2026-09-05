# Regression tests

`run_regression.py` runs both an unpatched `snesrecomp` checkout and
one with `patches/hirom_cop_support.patch` applied against the same
real per-game `.cfg` + ROM for several other games on the framework,
with `--game-cop-table` *not* passed, and asserts the two manifests
are deeply equal.

It expects sibling checkouts of the other games' repos (e.g.
`DKC2Recomp`, `MegaManX2Recomp`, `StarFoxSNESRecomp`,
`StarOceanSNESRecomp`, `SuperMarioWorldRecomp`,
`ZeldaAlttPSNESRecomp`) and your own legally-dumped ROMs for each,
at the paths set at the top of the script -- edit those paths for
your own machine before running. Not wired into CI (needs ROMs this
repo will never contain), but the intent is that anyone questioning
the "this patch is inert for other games" claim in `docs/FINDINGS.md`
can check it themselves instead of taking it on faith.

As of this writing: DKC2, Mega Man X2, Mega Man X3, Star Fox, Star
Ocean, Super Mario World, and Zelda: A Link to the Past all come back
identical.
