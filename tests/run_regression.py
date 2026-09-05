import subprocess
import sys
import pathlib
import hashlib

GAMES = [
    ("DKC2Recomp",
     "/home/claude/repo_DKC2Recomp/recomp",
     "/home/claude/rom2/Donkey Kong Country 2 - Diddy's Kong Quest (USA) (En,Fr) (Rev 1).sfc"),
    ("MegaManX2Recomp",
     "/home/claude/repo_MegaManX2Recomp/recomp",
     "/home/claude/rom2/Mega Man X2 (USA).sfc"),
    ("MegamanX3SNESRecomp",
     "/home/claude/repo_MegamanX3SNESRecomp/recomp",
     "/home/claude/rom2/Mega Man X3 (USA).sfc"),
    ("StarFoxSNESRecomp",
     "/home/claude/repo_StarFoxSNESRecomp/recomp",
     "/home/claude/rom2/Star Fox (USA) (Rev 2).sfc"),
    ("StarOceanSNESRecomp",
     "/home/claude/repo_StarOceanSNESRecomp/config",
     "/home/claude/rom2/Star Ocean (J) [!].smc"),
]

OUT = pathlib.Path("/home/claude/regression_manifests")
OUT.mkdir(exist_ok=True)


def run(analyzer_py, rom, cfgdir, manifest_out):
    cmd = ["python3", analyzer_py, "--rom", rom, "--cfg-dir", cfgdir,
           "--manifest", str(manifest_out)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def sha256(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


results = []
for name, cfgdir, rom in GAMES:
    if not pathlib.Path(rom).exists() or not pathlib.Path(cfgdir).exists():
        results.append((name, "SKIPPED (missing rom or cfgdir)", None))
        continue

    base_manifest = OUT / f"{name}_baseline.json"
    patched_manifest = OUT / f"{name}_patched.json"

    # BASELINE: the untouched, pre-patch snesrecomp checkout.
    rc1, out1, err1 = run(
        "/home/claude/snesrecomp_baseline_copy/tools/v2_analyze.py",
        rom, cfgdir, base_manifest)
    # PATCHED: the modified checkout, new flag NOT passed (must be inert).
    rc2, out2, err2 = run(
        "/home/claude/snesrecomp/tools/v2_analyze.py",
        rom, cfgdir, patched_manifest)

    if rc1 != 0 or rc2 != 0:
        results.append((name, f"RUN FAILED baseline_rc={rc1} patched_rc={rc2}",
                         (out1, err1, out2, err2)))
        continue

    identical_stdout = (out1 == out2)
    identical_file = (sha256(base_manifest) == sha256(patched_manifest))
    results.append((name,
                     "IDENTICAL" if (identical_stdout and identical_file)
                     else "DIFFERS",
                     (out1, out2, identical_stdout, identical_file)))

print("\n=== REGRESSION TEST: patched vs baseline, flag NOT passed ===\n")
for name, status, detail in results:
    print(f"{name}: {status}")
    if status == "DIFFERS":
        print("  baseline stdout:", detail[0])
        print("  patched  stdout:", detail[1])
    elif status.startswith("RUN FAILED"):
        print("  ", detail)
