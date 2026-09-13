#!/usr/bin/env python3
"""
screengraft -- the images a designer has actually used, per role.

The picker used to list whatever was newest on ~/Desktop and ~/Downloads. That
is a guess about where files live; this is a record of what was chosen. Every
source that reaches the session through /api/use or /api/upload is written
here, newest first, one list per role (a photograph of a device and a
screenshot to put on it are different populations), and the picker shows the
ones that still exist on disk.

Store: ~/.screengraft/recents.json
  {"photo": [{"path": ..., "name": ..., "used": <epoch>}, ...], "screenshot": [...]}

An uploaded file's path is its session copy, which the launch-time sweep
removes when nothing was saved from that session -- so an upload stays recent
only as long as its session does. A file chosen by path is read through in
place and stays for as long as the file does.

First run: seeds itself from the sessions that already exist, oldest first,
so the list is not empty for someone who has been using the tool for a week.
"""
import json
import os
import time

ROLES = ("photo", "screenshot")
CAP = 60


def store_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".screengraft", "recents.json")


def _load() -> dict:
    try:
        with open(store_path()) as f:
            d = json.load(f)
        if not isinstance(d, dict):
            raise ValueError
    except (OSError, ValueError):
        d = _seed()
    for r in ROLES:
        d.setdefault(r, [])
    return d


def _save(d: dict):
    p = store_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, p)


def _seed() -> dict:
    """Once: what the existing sessions say was used, in the order they ran."""
    d = {r: [] for r in ROLES}
    root = os.path.join(os.path.expanduser("~"), ".screengraft", "sessions")
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return d
    for n in names:
        sp = os.path.join(root, n, "state.json")
        try:
            with open(sp) as f:
                st = json.load(f)
            used = os.path.getmtime(sp)
        except (OSError, ValueError):
            continue
        for r in ROLES:
            p = st.get(r)
            if isinstance(p, str) and os.path.isfile(p):
                _push(d, r, p, used)
    return d


def _push(d: dict, role: str, path: str, used: float):
    lst = [e for e in d[role] if e.get("path") != path]
    lst.insert(0, {"path": path, "name": os.path.basename(path), "used": used})
    d[role] = lst[:CAP]


def record(role: str, path: str):
    if role not in ROLES or not path:
        return
    d = _load()
    _push(d, role, os.path.realpath(path), time.time())
    _save(d)


def items(role: str, limit: int = 40) -> list:
    """Newest-used first, only what still exists; dead entries are dropped."""
    if role not in ROLES:
        return []
    d = _load()
    live, out = [], []
    for e in d[role]:
        p = e.get("path")
        if not (isinstance(p, str) and os.path.isfile(p)):
            continue
        live.append(e)
        try:
            st = os.stat(p)
        except OSError:
            continue
        out.append({"path": p, "name": e.get("name") or os.path.basename(p), "used": e.get("used", 0),
                    "mtime": st.st_mtime, "bytes": st.st_size,
                    "ext": os.path.splitext(p)[1].lower(),
                    "folder": _short_folder(os.path.dirname(p))})
    if len(live) != len(d[role]):
        d[role] = live
        _save(d)
    return out[:limit]


def _short_folder(dirpath: str) -> str:
    home = os.path.expanduser("~")
    if dirpath.startswith(os.path.join(home, ".screengraft", "sessions")):
        return "dropped in"
    if dirpath.startswith(home + os.sep):
        return "~" + dirpath[len(home):]
    return dirpath
