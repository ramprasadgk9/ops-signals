"""Write the publication report (and the award report, where award.py exists) for one benchmark snapshot.

    .venv/bin/python -m benchmark.evidence benchmark/results/<run>

Writes evidence-publication.html into the snapshot folder, plus evidence-award.html when the local,
uncommitted award.py is present. Run benchmark.nab.official_score on the snapshot first to include
NAB's official scores.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from benchmark.evidence import paper
from benchmark.evidence.facts import build_facts

try:
    from benchmark.evidence import award
except ImportError:  # award.py is kept local and isn't in the repository
    award = None


def write(snapshot: Path) -> list[Path]:
    facts = build_facts(snapshot)
    paper_path = snapshot / "evidence-publication.html"
    paper_path.write_text(paper.render(facts), encoding="utf-8")
    written = [paper_path]
    if award is not None:
        award_path = snapshot / "evidence-award.html"
        award_path.write_text(award.render(facts), encoding="utf-8")
        written.insert(0, award_path)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("snapshot", type=Path, help="A benchmark snapshot folder (benchmark/results/<run>/)")
    for path in write(parser.parse_args().snapshot):
        print(path)


if __name__ == "__main__":
    main()
