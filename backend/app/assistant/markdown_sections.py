"""Splits a Markdown document into its heading-delimited sections.

Each section keeps its full heading path ("Security model > Turning on authentication > Clients")
and the GitHub-style anchor of its own heading, so a retrieved chunk can be cited down to the
section it came from, and linked to, rather than only to the file it lives in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


@dataclass(slots=True)
class MarkdownSection:
    heading_path: list[str] = field(default_factory=list)
    anchor: str = ""
    level: int = 0
    # The section's own text only, starting at its heading line - not its subsections'.
    text: str = ""

    @property
    def heading(self) -> str:
        return self.heading_path[-1] if self.heading_path else ""

    @property
    def breadcrumb(self) -> str:
        return " > ".join(self.heading_path)


def github_anchor(heading: str, seen: dict[str, int] | None = None) -> str:
    """The anchor GitHub generates for a heading: lowercase, punctuation dropped, each space a
    hyphen (so "Alertmanager → Slack" becomes "alertmanager--slack"), and a -1, -2... suffix for
    repeats within the same document when `seen` is passed."""
    text = re.sub(r"`|\*\*|__", "", heading).strip().lower()
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    slug = "".join(char for char in text if char.isalnum() or char in " -_").replace(" ", "-")
    if seen is None:
        return slug
    count = seen.get(slug, 0)
    seen[slug] = count + 1
    return slug if count == 0 else f"{slug}-{count}"


def split_sections(content: str) -> list[MarkdownSection]:
    """Every section of `content`, in document order. Text before the first heading becomes a
    section with an empty heading path. Headings inside fenced code blocks (a `# comment` in a
    bash snippet) are not headings."""
    sections: list[MarkdownSection] = []
    stack: list[tuple[int, str]] = []
    seen_anchors: dict[str, int] = {}
    current = MarkdownSection()
    lines: list[str] = []
    in_fence = False

    for line in content.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        match = None if in_fence else _HEADING.match(line)
        if match:
            current.text = "\n".join(lines).strip()
            if current.text:
                sections.append(current)
            level, heading = len(match.group(1)), match.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, heading))
            current = MarkdownSection(
                heading_path=[title for _, title in stack],
                anchor=github_anchor(heading, seen_anchors),
                level=level,
            )
            lines = [line]
            continue
        lines.append(line)

    current.text = "\n".join(lines).strip()
    if current.text:
        sections.append(current)
    return sections
