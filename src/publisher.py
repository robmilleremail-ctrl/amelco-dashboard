"""
Publishes the latest password-protected dashboard to GitHub Pages (gh-pages branch).

Uses git plumbing commands so the working directory is never touched — safe to call
from inside a running server without branch-switching side effects.
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path


PAGES_URL = "https://robmilleremail-ctrl.github.io/amelco-dashboard/"


def publish(project_root: Path, output_dir: Path) -> tuple[bool, str]:
    """
    Push the latest *-protected.html as index.html on the gh-pages branch.

    Returns (success: bool, message: str).
    """
    # ── Find latest protected report ─────────────────────────────────────────
    protected = sorted(output_dir.glob("amelco-dashboard-*-protected.html"))
    if not protected:
        return False, "No protected report found — run main.py first."
    latest = protected[-1]
    content = latest.read_bytes()

    def run(*args, **kwargs):
        return subprocess.run(list(args), cwd=str(project_root), **kwargs)

    try:
        # ── Fetch latest remote gh-pages state ───────────────────────────────
        run("git", "fetch", "origin", "gh-pages",
            check=True, capture_output=True)

        # ── Create a blob for index.html ─────────────────────────────────────
        blob_result = run(
            "git", "hash-object", "-w", "--stdin",
            input=content, capture_output=True, check=True
        )
        blob = blob_result.stdout.strip().decode()

        # ── Build a tree containing only index.html ──────────────────────────
        tree_result = run(
            "git", "mktree",
            input=f"100644 blob {blob}\tindex.html\n".encode(),
            capture_output=True, check=True
        )
        tree = tree_result.stdout.strip().decode()

        # ── Get the current remote gh-pages HEAD as parent ───────────────────
        parent_result = run(
            "git", "rev-parse", "origin/gh-pages",
            capture_output=True
        )
        parent = parent_result.stdout.strip().decode() if parent_result.returncode == 0 else None

        # ── Create the commit ─────────────────────────────────────────────────
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        commit_args = ["git", "commit-tree", tree, "-m", f"Publish dashboard {stamp}"]
        if parent:
            commit_args += ["-p", parent]
        commit = run(*commit_args, capture_output=True, check=True).stdout.strip().decode()

        # ── Push to origin/gh-pages ───────────────────────────────────────────
        run("git", "push", "origin", f"{commit}:refs/heads/gh-pages",
            capture_output=True, check=True)

        # ── Update local ref so next publish has the right parent ─────────────
        run("git", "update-ref", "refs/heads/gh-pages", commit, capture_output=True)

        print(f"[publisher] Published → {PAGES_URL}")
        return True, PAGES_URL

    except subprocess.CalledProcessError as e:
        err = (e.stderr or b"").decode()[:400]
        return False, f"Publish failed: {err}"
    except Exception as e:
        return False, f"Publish error: {e}"
