"""Fetch a public benchmark dataset at a pinned version into the gitignored cache.

Repositories are checked out at a pinned commit; plain downloads are pinned by SHA-256. Harnesses
read data and labels from these copies. Pinning means a result names exactly which version of a
dataset it was measured on, and fetching rather than vendoring keeps third-party data out of this
repository.
"""

from __future__ import annotations

import hashlib
import subprocess
import urllib.request
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


def ensure_download(url: str, sha256: str, path: Path) -> Path:
    """Return `path` holding the file at `url` with exactly `sha256`, downloading it if needed."""
    if path.exists() and file_sha256(path) == sha256:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    try:
        with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as handle:
            while chunk := response.read(1 << 20):
                handle.write(chunk)
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise CheckoutError(f"download of {url} failed: {exc}") from exc
    actual = file_sha256(partial)
    if actual != sha256:
        partial.unlink(missing_ok=True)
        raise CheckoutError(f"{url} has SHA-256 {actual}, expected pinned {sha256}")
    partial.replace(path)
    return path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()
