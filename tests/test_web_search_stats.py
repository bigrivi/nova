import importlib
import json
import time

from nova.tools.web_search.stats import (
    OUTCOME_EMPTY,
    OUTCOME_OK,
    OUTCOME_RATE_LIMITED,
    record_usage,
    render,
    summarize,
    usage_path,
)


def _write_records(records) -> None:
    path = usage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )


def _record(backend, outcome, age_seconds=0.0):
    return {
        "ts": time.time() - age_seconds,
        "backend": backend,
        "outcome": outcome,
    }


def test_record_usage_appends_one_json_object_per_call():
    for _ in range(3):
        record_usage("exa", OUTCOME_OK)

    lines = usage_path().read_text(encoding="utf-8").splitlines()

    assert len(lines) == 3
    parsed = [json.loads(line) for line in lines]
    assert {record["backend"] for record in parsed} == {"exa"}
    assert {record["outcome"] for record in parsed} == {OUTCOME_OK}
    assert all("ts" in record for record in parsed)


def test_record_usage_never_raises_when_the_log_is_unwritable(monkeypatch, tmp_path):
    """A log that cannot be created must not break the search that logged it.

    ``nova.tools.web_search`` resolves to the tool function rather than this
    package, so the module is fetched through importlib instead of by name.
    """
    module = importlib.import_module("nova.tools.web_search.stats")
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(module, "usage_path", lambda: blocker / "logs" / "usage.jsonl")

    module.record_usage("exa", module.OUTCOME_OK)

    assert not (blocker / "logs").exists()


def test_summarize_counts_each_outcome_per_backend_and_day():
    _write_records(
        [
            _record("exa", OUTCOME_OK),
            _record("exa", OUTCOME_OK),
            _record("exa", OUTCOME_RATE_LIMITED),
            _record("parallel", OUTCOME_OK),
            _record("parallel", OUTCOME_EMPTY),
            _record("parallel", "transport"),
        ]
    )

    rows = summarize(days=1)
    by_backend = {row["backend"]: row for row in rows}

    assert by_backend["exa"]["ok"] == 2
    assert by_backend["exa"]["rate_limited"] == 1
    assert by_backend["exa"]["empty"] == 0
    assert by_backend["parallel"]["ok"] == 1
    assert by_backend["parallel"]["empty"] == 1
    assert by_backend["parallel"]["other_errors"] == 1
    assert by_backend["parallel"]["total"] == 3


def test_summarize_excludes_records_older_than_the_window():
    _write_records(
        [
            _record("exa", OUTCOME_OK),
            _record("exa", OUTCOME_OK, age_seconds=3 * 86400),
        ]
    )

    rows = summarize(days=1)

    assert sum(row["ok"] for row in rows) == 1


def test_summarize_returns_nothing_when_no_log_exists():
    assert summarize(days=7) == []


def test_summarize_skips_corrupt_lines():
    path = usage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                json.dumps(_record("exa", OUTCOME_OK)),
                "not json at all",
                json.dumps({"backend": "exa"}),
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rows = summarize(days=1)

    assert sum(row["ok"] for row in rows) == 1


def test_summarize_orders_newest_day_first():
    _write_records(
        [
            _record("exa", OUTCOME_OK, age_seconds=2 * 86400),
            _record("exa", OUTCOME_OK),
        ]
    )

    rows = summarize(days=7)

    assert len(rows) == 2
    assert rows[0]["date"] >= rows[1]["date"]


def test_render_explains_an_empty_log():
    assert "No web_search usage recorded yet" in render([])


def test_render_lists_every_backend_column(capsys):
    _write_records(
        [
            _record("exa", OUTCOME_OK),
            _record("parallel", OUTCOME_RATE_LIMITED),
        ]
    )

    output = render(summarize(days=1))

    assert "backend" in output
    assert "exa" in output
    assert "parallel" in output
    assert "429" in output
    assert str(usage_path()) in output
