"""Every doc section says something itself. Ask Ops Signals quotes only a section's own text, so a
section that is nothing but "See [LICENSE](LICENSE)." gives it nothing to answer with (see
docs/ask-ops-signals-assistant.md, "Writing Docs the Assistant Can Answer From")."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"(?<!!)\[[^\]]*\]\([^)]*\)")
IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
HEADING = re.compile(r"^(#{1,6})\s+(.*)")
FILLER = re.compile(r"\b(see|read|in|the|and|also|for|details?)\b", re.IGNORECASE)
# Sections whose whole point is a list of links.
LINK_LIST_HEADINGS = re.compile(r"^(learn more|see also|related|further reading|links)\b", re.IGNORECASE)


def _tracked_docs() -> list[Path]:
    # Tracked files only: local, gitignored docs are the author's business.
    try:
        out = subprocess.check_output(["git", "ls-files", "README.md", "docs/*.md", "docs/**/*.md"], cwd=ROOT, text=True)
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git is not available to list tracked docs")
    # A doc deleted but not yet staged is still listed by git.
    return [ROOT / path for path in out.split() if "/archive/" not in path and (ROOT / path).exists()]


def _sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    heading: str | None = None
    body: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
        match = None if in_fence else HEADING.match(line)
        if match:
            if heading is not None:
                sections.append((heading, "\n".join(body).strip()))
            heading, body = match.group(2).strip(), []
        else:
            body.append(line)
    if heading is not None:
        sections.append((heading, "\n".join(body).strip()))
    return sections


def link_only_sections(text: str) -> list[str]:
    """Headings of sections whose own text is only links, e.g. "See [LICENSE](LICENSE)."."""
    found = []
    for heading, body in _sections(text):
        body = IMAGE.sub("", body)
        if not LINK.search(body) or LINK_LIST_HEADINGS.match(heading):
            continue
        rest = FILLER.sub("", LINK.sub("", body))
        if not re.search(r"[A-Za-z0-9]{2,}", rest):
            found.append(heading)
    return found


def test_link_only_sections_are_found() -> None:
    text = "# Doc\n\nIntro.\n\n## License\n\nSee [LICENSE](LICENSE).\n\n## Learn More\n\n- [A](a.md)\n\n## Shot\n\n![x](x.png)\n"
    assert link_only_sections(text) == ["License"]


def test_a_section_that_answers_before_linking_passes() -> None:
    text = "# Doc\n\n## License\n\nOps Signals is open source under the MIT license. See [LICENSE](LICENSE).\n"
    assert link_only_sections(text) == []


def test_no_doc_section_only_points_elsewhere() -> None:
    problems = [
        f"{path.relative_to(ROOT)} > {heading}"
        for path in _tracked_docs()
        for heading in link_only_sections(path.read_text(encoding="utf-8"))
    ]
    assert problems == [], "Sections with nothing but a link; write the answer, then link: " + "; ".join(problems)
