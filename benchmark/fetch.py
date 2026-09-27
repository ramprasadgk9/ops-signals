"""Check out a public benchmark repository at a pinned commit into the gitignored cache.

Harnesses read data and labels from these checkouts. Pinning the commit means a result names
exactly which version of a dataset it was measured on, and fetching rather than vendoring keeps
third-party data out of this repository.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from benchmark.router_benchmark import PROJECT_ROOT

CACHE_DIR = PROJECT_ROOT / "benchmark" / ".cache"


class CheckoutError(RuntimeError):
    """Raised when a repository can't be cloned or checked out at the pinned commit."""


def ensure_checkout(repository: str, commit: str, cache_dir: Path, required: tuple[str, ...] = ()) -> Path:
    """Return a checkout of `repository` at exactly `commit`, cloning or updating the cache as needed."""
    if not (cache_dir / ".git").exists():
        cache_dir.parent.mkdir(parents=True, exist_ok=True)
        git(cache_dir.parent, "clone", "--quiet", repository, cache_dir.name)
    if head(cache_dir) != commit:
        try:
            git(cache_dir, "checkout", "--quiet", commit)
        except CheckoutError:
            git(cache_dir, "fetch", "--quiet", "origin")
            git(cache_dir, "checkout", "--quiet", commit)
    current = head(cache_dir)
    if current != commit:
        raise CheckoutError(f"{cache_dir} is at {current}, expected pinned commit {commit}")
    for path in required:
        if not (cache_dir / path).exists():
            raise CheckoutError(f"{cache_dir} is missing {path}")
    return cache_dir


def head(cache_dir: Path) -> str:
    return git(cache_dir, "rev-parse", "HEAD").strip()


def git(cwd: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise CheckoutError(f"git {' '.join(args)} failed: {detail.strip()}") from exc
