"""Write the award and publication reports for one benchmark snapshot.

    .venv/bin/python -m benchmark.evidence benchmark/results/<run>

Writes evidence-award.html and evidence-publication.html into the snapshot folder. Run
benchmark.nab.official_score on the snapshot first to include NAB's official scores.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from benchmark.evidence import award, paper
from benchmark.evidence.facts import build_facts


def write(snapshot: Path) -> tuple[Path, Path]:
    facts = build_facts(snapshot)
    award_path, paper_path = snapshot / "evidence-award.html", snapshot / "evidence-publication.html"
    award_path.write_text(award.render(facts), encoding="utf-8")
    paper_path.write_text(paper.render(facts), encoding="utf-8")
    return award_path, paper_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("snapshot", type=Path, help="A benchmark snapshot folder (benchmark/results/<run>/)")
    for path in write(parser.parse_args().snapshot):
        print(path)


if __name__ == "__main__":
    main()
