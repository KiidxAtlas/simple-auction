"""Updates for a copy run from source (a git checkout, e.g. on a Mac).

The installed Windows app updates through release installers (updates.py);
a checkout updates by pulling new commits from GitHub instead.
"""

import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import simple_auction

log = logging.getLogger(__name__)

GIT_TIMEOUT = 60
SYNC_TIMEOUT = 300


class SourceUpdateError(Exception):
    """git (or uv) failed; the message is meant for the user."""


@dataclass
class SourceStatus:
    behind: int  # commits on GitHub not yet pulled
    changes: list[str] = field(default_factory=list)  # their one-line summaries
    local_changes: bool = False  # uncommitted edits in the checkout


def repo_root() -> Path | None:
    """The git checkout this code runs from, or None (installed app, pip)."""
    if getattr(sys, "frozen", False):
        return None
    root = Path(simple_auction.__file__).resolve().parents[2]
    return root if (root / ".git").exists() else None


def _run(args: list[str], root: Path, timeout: int = GIT_TIMEOUT) -> str:
    try:
        done = subprocess.run(
            args,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as e:
        raise SourceUpdateError(f"{args[0]} isn't installed or isn't on PATH.") from e
    except subprocess.TimeoutExpired as e:
        raise SourceUpdateError(f"'{' '.join(args[:2])}' took too long.") from e
    if done.returncode != 0:
        message = (done.stderr or done.stdout).strip() or f"exit code {done.returncode}"
        raise SourceUpdateError(message)
    return done.stdout.strip()


def check(root: Path) -> SourceStatus:
    """Fetch from GitHub and report how far behind this checkout is."""
    _run(["git", "fetch", "--quiet", "origin"], root)
    try:
        _run(["git", "rev-parse", "--abbrev-ref", "@{upstream}"], root)
    except SourceUpdateError as e:
        raise SourceUpdateError(
            "This branch isn't tracking a branch on GitHub, so there's "
            "nothing to update from."
        ) from e
    behind = int(_run(["git", "rev-list", "--count", "HEAD..@{upstream}"], root))
    changes = []
    if behind:
        log_lines = _run(["git", "log", "--format=%s", "HEAD..@{upstream}"], root)
        changes = [line for line in log_lines.splitlines() if line.strip()]
    local = bool(_run(["git", "status", "--porcelain", "--untracked-files=no"], root))
    return SourceStatus(behind=behind, changes=changes, local_changes=local)


def apply(root: Path, *, sync: bool = True) -> None:
    """Pull the new commits (fast-forward only, so nothing is ever merged or
    overwritten), then bring installed packages up to date with uv."""
    # Override the user's git settings: with pull.rebase / autostash on, git
    # would stash local edits, pull, and write conflict markers into source
    # files. Fast-forward only, no stash: on a conflict git just refuses.
    _run(
        [
            "git",
            "-c",
            "pull.rebase=false",
            "-c",
            "rebase.autoStash=false",
            "-c",
            "merge.autoStash=false",
            "pull",
            "--ff-only",
            "--no-rebase",
            "--quiet",
        ],
        root,
    )
    if sync and (uv := shutil.which("uv")):
        _run([uv, "sync", "--quiet"], root, timeout=SYNC_TIMEOUT)


def restart_command() -> list[str]:
    """How to start the app again with the same Python."""
    return [sys.executable, "-m", "simple_auction"]
