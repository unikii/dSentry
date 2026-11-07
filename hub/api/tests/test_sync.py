"""Repository-level generated-artifact consistency checks."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_vendored_metrics_schema_matches_source():
    source = REPO_ROOT / "schemas" / "metrics_schema.json"
    vendored = REPO_ROOT / "hub" / "ui" / "src" / "lib" / "metrics-schema.json"
    assert source.read_bytes() == vendored.read_bytes(), (
        "hub/ui/src/lib/metrics-schema.json is out of sync with "
        "schemas/metrics_schema.json"
    )
