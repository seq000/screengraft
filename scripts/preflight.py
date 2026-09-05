#!/usr/bin/env python3
"""
screengraft — preflight. Run this first, every time.

Reports what the plugin needs and whether it's there, as JSON, so the skill
can tell the user plainly what's missing before promising anything.

  python3 scripts/preflight.py            -> JSON report, exit 0 if ready, 1 if not
  python3 scripts/preflight.py --install  -> create ~/.screengraft/venv and install
                                             requirements.txt into it (only run this
                                             after the user has said yes)

OpenCV is a HARD requirement: it is the engine. Without it nothing runs — not
"results will be worse", nothing. Say exactly that. Optional extras (SAM 2,
later) are the tier where "works, but worse without" applies.

The venv lives outside the plugin folder (~/.screengraft/venv) so it survives
plugin updates and never touches the user's system Python.
"""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REQ = os.path.join(HERE, "requirements.txt")
VENV = os.path.expanduser("~/.screengraft/venv")
VENV_PY = os.path.join(VENV, "bin", "python")

REQUIRED = [
    ("cv2", "opencv-python-headless", "The engine: homography, warp, detection. Nothing runs without it."),
    ("numpy", "numpy", "Array math for the compositing step."),
]


def probe(pyexe: str):
    """Ask a given python which required modules import."""
    code = (
        "import json,importlib\n"
        "out={}\n"
        "for m in %r:\n"
        "    try:\n"
        "        mod=importlib.import_module(m); out[m]=getattr(mod,'__version__','ok')\n"
        "    except Exception as e:\n"
        "        out[m]=None\n"
        "print(json.dumps(out))"
    ) % [m for m, _, _ in REQUIRED]
    try:
        r = subprocess.run([pyexe, "-c", code], capture_output=True, text=True, timeout=60)
        return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else {m: None for m, _, _ in REQUIRED}
    except Exception:
        return {m: None for m, _, _ in REQUIRED}


def report():
    py_candidates = []
    if os.path.exists(VENV_PY):
        py_candidates.append(("venv", VENV_PY))
    py_candidates.append(("system", sys.executable))

    chosen = None
    probes = {}
    for label, exe in py_candidates:
        found = probe(exe)
        probes[label] = {"python": exe, "modules": found}
        if all(found.get(m) for m, _, _ in REQUIRED) and chosen is None:
            chosen = (label, exe)

    missing = [] if chosen else [
        {"module": m, "pip": pkg, "why": why}
        for m, pkg, why in REQUIRED
        if not probes[py_candidates[0][0]]["modules"].get(m)
    ]
    return {
        "ready": chosen is not None,
        "python": chosen[1] if chosen else None,
        "python_source": chosen[0] if chosen else None,
        "platform": platform.platform(),
        "venv": VENV,
        "venv_exists": os.path.exists(VENV_PY),
        "probes": probes,
        "missing": missing,
        "hard_requirement": "OpenCV is the engine. Without it screengraft cannot run at all — this is not a degraded mode, it is no mode.",
        "install_command": f"{sys.executable} {os.path.abspath(__file__)} --install",
        "install_does": f"Creates a virtualenv at {VENV} (nothing touches system Python) and pip-installs "
                        f"{', '.join(pkg for _, pkg, _ in REQUIRED)} into it (~60 MB download).",
        "optional": [
            {"name": "SAM 2 (M4)", "status": "not yet used by the plugin",
             "why": "Better screen detection on photos where tone-based detection fails. Optional; results are worse without it, not absent."}
        ],
        "tools": {"open_browser": shutil.which("open") or shutil.which("xdg-open")},
    }


def install():
    os.makedirs(os.path.dirname(VENV), exist_ok=True)
    if not os.path.exists(VENV_PY):
        subprocess.check_call([sys.executable, "-m", "venv", VENV])
    subprocess.check_call([VENV_PY, "-m", "pip", "install", "-q", "--upgrade", "pip"])
    subprocess.check_call([VENV_PY, "-m", "pip", "install", "-q", "-r", REQ])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--install", action="store_true", help="Create the venv and install requirements (ask the user first)")
    args = ap.parse_args()
    if args.install:
        install()
    rep = report()
    print(json.dumps(rep, indent=1))
    sys.exit(0 if rep["ready"] else 1)


if __name__ == "__main__":
    main()
