"""Turn CI's backend junit report into pytest-split's durations file.

CI splits the backend tests into parallel groups by duration (pytest-split reads
``backend/.test_durations``). Refresh the file when the groups drift apart:

    gh run download <run-id> -n backend-junit-1 -n backend-junit-2 -D /tmp/junit
    python scripts/test_durations.py /tmp/junit/*/junit.xml > backend/.test_durations

Times include setup and teardown, which is what a test costs its group. Tests missing from
the file (new ones) count as the average, so a stale file only makes the groups less even.
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET


def node_id(classname: str, name: str) -> str:
    """``tutortrack.core.tests.test_api.TestX`` + ``test_y`` → pytest's node id."""
    module, _, cls = classname.rpartition(".")
    if cls[:1].isupper():  # a test class
        return f"{module.replace('.', '/')}.py::{cls}::{name}"
    return f"{classname.replace('.', '/')}.py::{name}"


def main(paths: list[str]) -> None:
    durations: dict[str, float] = {}
    for path in paths:
        # Our own CI artifact, not untrusted input.
        for case in ET.parse(path).getroot().iter("testcase"):  # noqa: S314
            if case.find("skipped") is not None:
                continue
            nid = node_id(case.get("classname", ""), case.get("name", ""))
            durations[nid] = round(float(case.get("time", 0)), 3)
    # junit charges each xdist worker's session setup to its first test: flag outliers.
    for nid, seconds in durations.items():
        if seconds > 120:
            sys.stderr.write(f"warning: {nid} took {seconds}s (session setup?)\n")
    json.dump(dict(sorted(durations.items())), sys.stdout, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main(sys.argv[1:])
