"""Source (git checkout) updates, against throwaway local repositories."""

import os
import subprocess
from pathlib import Path

import pytest

from simple_auction.services import source_update
from simple_auction.services.source_update import SourceUpdateError, apply, check

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull,  # ignore the user's git settings
}


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, env=GIT_ENV, check=True, capture_output=True, text=True
    ).stdout


def commit(repo: Path, name: str, text: str, message: str) -> None:
    (repo / name).write_text(text)
    git("add", name, cwd=repo)
    git("commit", "-q", "-m", message, cwd=repo)


@pytest.fixture
def repos(tmp_path, monkeypatch):
    """(origin on "GitHub", the user's checkout, another clone that pushes)."""
    # The app's own git calls get the same identity, but keep the user's real
    # git settings (autostash etc.) so the tests cover them.
    for name in (
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
    ):
        monkeypatch.setenv(name, GIT_ENV[name])
    origin = tmp_path / "origin.git"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    mine = tmp_path / "mine"
    git("clone", "-q", str(origin), str(mine), cwd=tmp_path)
    commit(mine, "app.txt", "v1", "First version")
    git("push", "-q", "-u", "origin", "main", cwd=mine)
    other = tmp_path / "other"
    git("clone", "-q", str(origin), str(other), cwd=tmp_path)
    return origin, mine, other


def test_up_to_date(repos):
    _, mine, _ = repos
    status = check(mine)
    assert status.behind == 0 and status.changes == []


def test_reports_new_commits_and_pulls_them(repos):
    _, mine, other = repos
    commit(other, "app.txt", "v2", "Add import")
    commit(other, "app.txt", "v3", "Fix update dialog")
    git("push", "-q", cwd=other)

    status = check(mine)
    assert status.behind == 2
    assert status.changes == ["Fix update dialog", "Add import"]

    apply(mine, sync=False)
    assert (mine / "app.txt").read_text() == "v3"
    assert check(mine).behind == 0


def test_local_edits_are_reported_and_kept(repos):
    _, mine, other = repos
    commit(other, "other.txt", "x", "Unrelated change")
    git("push", "-q", cwd=other)
    (mine / "app.txt").write_text("my edit")

    assert check(mine).local_changes
    apply(mine, sync=False)
    assert (mine / "app.txt").read_text() == "my edit"  # untouched
    assert (mine / "other.txt").exists()


def test_conflicting_local_edit_fails_without_losing_it(repos, monkeypatch):
    # Even with autostash-on-pull switched on, as in many git setups.
    config = repos[1].parent / "gitconfig"
    config.write_text("[pull]\n\trebase = true\n[rebase]\n\tautostash = true\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    _, mine, other = repos
    commit(other, "app.txt", "v2", "Change app")
    git("push", "-q", cwd=other)
    (mine / "app.txt").write_text("my edit")
    check(mine)

    with pytest.raises(SourceUpdateError):
        apply(mine, sync=False)
    assert (mine / "app.txt").read_text() == "my edit"  # no conflict markers
    assert git("stash", "list", cwd=mine) == ""


def test_branch_without_upstream(repos):
    _, mine, _ = repos
    git("checkout", "-q", "-b", "experiment", cwd=mine)
    with pytest.raises(SourceUpdateError, match="isn't tracking"):
        check(mine)


def test_repo_root_is_this_checkout_when_run_from_source():
    root = source_update.repo_root()
    assert root is not None and (root / "pyproject.toml").exists()
