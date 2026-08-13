"""Parse the skill-hierarchy Excel file into ``src/iae/config/topics.yaml``.

Run this whenever the spreadsheet changes so the API can load Topic IDs
without opening ``.xlsx`` on every request.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from iae.core.settings import get_settings
from iae.core.skills import dump_topics_yaml, match_curriculum_chapters, parse_skill_workbook

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "src" / "iae" / "config" / "topics.yaml"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--xlsx",
        type=Path,
        default=None,
        help="Override SKILLS_XLSX_PATH from .env.",
    )
    args = parser.parse_args()

    xlsx = args.xlsx or Path(get_settings().skills_xlsx_path)
    if not xlsx.exists():
        print(f"Excel not found: {xlsx}", file=sys.stderr)
        return 1

    topics = parse_skill_workbook(xlsx)
    if not topics:
        print(f"No Topic ID rows parsed from {xlsx}", file=sys.stderr)
        return 2

    dump_topics_yaml(topics, OUTPUT_PATH)
    print(f"Wrote {len(topics)} topics to {OUTPUT_PATH}")

    by_grade: dict[int, int] = {}
    for topic in topics:
        by_grade[topic.grade] = by_grade.get(topic.grade, 0) + 1
    for grade, count in sorted(by_grade.items()):
        matched, unmatched = match_curriculum_chapters(grade)
        print(f"  G{grade}: {count} topic ids, {len(matched)} curriculum chapter matches")
        for title in unmatched:
            print(f"    unmatched Excel chapter: {title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
