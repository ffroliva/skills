"""git, behind the SourceControl port."""

from __future__ import annotations

from ..ports import CommandRunner


class GitCli:
    def __init__(self, run: CommandRunner) -> None:
        self._run = run

    def resolve(self, ref: str) -> str:
        done = self._run(["git", "rev-parse", "--verify", f"{ref}^{{commit}}"])
        return done.out.strip() if done.rc == 0 else ""

    def _tips(self, remote: str) -> set[str] | None:
        """Branch and tag tips only. `git clone` fetches no refs/pull/*, so a commit reachable only there cannot run."""
        done = self._run(["git", "ls-remote", "--heads", "--tags", remote])
        return {line.split("\t")[0] for line in done.out.splitlines() if line.strip()} if done.rc == 0 else None

    def remote_readable(self, remote: str) -> bool:
        return self._tips(remote) is not None

    def on_remote(self, sha: str, remote: str) -> bool:
        """True when a clone of `remote` has `sha`: at a tip, or below one this clone knows. Fetch first if it says no."""
        tips = self._tips(remote)
        if not sha or tips is None:
            return False
        if sha in tips:
            return True
        below = self._run(["git", "for-each-ref", "--contains", sha, "--format=%(objectname)", "refs/remotes", "refs/tags"])
        return below.rc == 0 and bool(tips & set(below.out.split()))

    def dirty(self) -> bool:
        return bool(self._run(["git", "status", "--porcelain", "--untracked-files=no"]).out.strip())
