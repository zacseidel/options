"""Publish the built site to GitHub Pages (branch `gh-pages`, served from its root).

Each run replaces the branch with one fresh commit holding site/index.html, css, js and the exported data, so the
repository doesn't grow with every day's data (the encrypted files change completely on every export). `main` and
the working tree are never touched: the commit is built with a separate index file and pushed by hash.

Refuses to publish data that isn't encrypted: site/data/lock.json must exist (set SITE_PASSWORD in .env).

Usage:  python -m market.ops.publish
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from market.config import ROOT, directory

BRANCH = "gh-pages"
REMOTE = "origin"
SITE_FILES = ["index.html", "css", "js"]


def _git(*args: str, env: dict | None = None) -> str:
    out = subprocess.run(["git", *args], cwd=ROOT, env=env, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {out.stderr.strip()[:300]}")
    return out.stdout.strip()


def publish() -> dict:
    site, data = ROOT / "site", directory("site_out")
    if not (data / "lock.json").exists():
        raise RuntimeError("site/data is not encrypted (no lock.json): set SITE_PASSWORD in .env and re-export first")
    with tempfile.TemporaryDirectory() as tmp:
        build = Path(tmp) / "site"
        build.mkdir()
        for name in SITE_FILES:
            src = site / name
            (shutil.copytree if src.is_dir() else shutil.copy2)(src, build / name)
        shutil.copytree(data, build / "data")
        (build / ".nojekyll").write_text("")            # serve files as they are (no Jekyll processing)
        # The build's objects go to a throwaway object store (the repo's own objects are read through
        # alternates), so the local .git doesn't grow by a site build every day; it is deleted with `tmp`.
        objects = Path(tmp) / "objects"
        objects.mkdir()
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index"), "GIT_OBJECT_DIRECTORY": str(objects),
               "GIT_ALTERNATE_OBJECT_DIRECTORIES": _git("rev-parse", "--path-format=absolute", "--git-path", "objects")}
        _git("--work-tree", str(build), "add", "-A", ".", env=env)
        tree = _git("write-tree", env=env)
        files = len(_git("ls-tree", "-r", "--name-only", tree, env=env).splitlines())
        size = sum(p.stat().st_size for p in build.rglob("*") if p.is_file())
        commit = _git("commit-tree", tree, "-m", f"Site build {datetime.now():%Y-%m-%d %H:%M}", env=env)
        # A large post buffer: the default fails with HTTP 400 on a push of this size over HTTPS.
        _git("-c", "http.postBuffer=524288000", "push", "--force", "--quiet", REMOTE, f"{commit}:refs/heads/{BRANCH}", env=env)
    # The push may record origin/gh-pages locally, pointing at objects that left with the throwaway store; drop it so
    # git doesn't report a broken ref. (This clone also fetches only main: remote.origin.fetch.)
    subprocess.run(["git", "update-ref", "-d", f"refs/remotes/{REMOTE}/{BRANCH}"], cwd=ROOT, capture_output=True)
    return {"branch": BRANCH, "commit": commit[:8], "files": files, "mb": round(size / 1e6, 1)}


def main() -> None:
    print(publish())


if __name__ == "__main__":
    main()
