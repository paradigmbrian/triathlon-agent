from datetime import date

from typer.testing import CliRunner

from tri_wellness.cli import app, make_editor
from tri_wellness.labs.models import LabResult, RawResult, Unmapped
from tri_wellness.ranges.registry import MARKERS_PATH, load_registry
from tri_wellness.repl import review_to_yaml

runner = CliRunner()


def payload(**over):
    base = {
        "source_path": "/labs/aug.pdf",
        "drawn_on": "2026-08-20",
        "lab_name": "Quest",
        "results": [
            LabResult(
                marker="ferritin",
                value=42.0,
                unit="ng/mL",
                raw=RawResult(name="Ferritin, Serum", value="42", unit="ng/mL"),
                lab_ref_low=30.0,
                lab_ref_high=400.0,
            ).model_dump(mode="json"),
        ],
        "unmapped": [
            Unmapped(
                raw=RawResult(name="Sed Rate", value="4", unit="mm/h"), reason="name"
            ).model_dump(mode="json"),
        ],
        "context": None,
        "duplicates": [],
        "last_error": None,
    }
    base.update(over)
    return base


def test_help_lists_ingest():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0 and "ingest" in result.output


def test_ingest_unknown_extension_needs_kind(tmp_path):
    f = tmp_path / "panel.txt"
    f.write_text("x")
    result = runner.invoke(app, ["ingest", str(f)])
    assert result.exit_code == 2 and "--kind" in result.output


def test_ingest_missing_file_is_a_usage_error(tmp_path):
    result = runner.invoke(app, ["ingest", str(tmp_path / "nope.pdf")])
    assert result.exit_code == 2


def test_ingest_bad_drawn_on(tmp_path, tiny_pdf):
    result = runner.invoke(app, ["ingest", str(tiny_pdf), "--drawn-on", "yesterday"])
    assert result.exit_code == 2 and "YYYY-MM-DD" in result.output


async def test_make_editor_returns_edited_fields_on_valid_yaml(monkeypatch, capsys):
    reg = load_registry("male", MARKERS_PATH)
    p = payload()
    edited_yaml = review_to_yaml(p).replace("2026-08-20", "2026-08-21")

    def fake_call(args):
        with open(args[1], "w", encoding="utf-8") as fh:
            fh.write(edited_yaml)
        return 0

    monkeypatch.setattr("tri_wellness.cli.subprocess.call", fake_call)
    edit = make_editor(reg)
    result = await edit(p)
    assert result is not None and result["drawn_on"] == date(2026, 8, 21)


async def test_make_editor_returns_none_and_prints_on_invalid_yaml(monkeypatch, capsys):
    reg = load_registry("male", MARKERS_PATH)
    p = payload()

    def fake_call(args):
        with open(args[1], "w", encoding="utf-8") as fh:
            fh.write("results: [\n  - marker: ferritin\n")
        return 0

    monkeypatch.setattr("tri_wellness.cli.subprocess.call", fake_call)
    edit = make_editor(reg)
    result = await edit(p)
    assert result is None
    assert "edited YAML is not valid" in capsys.readouterr().out


async def test_make_editor_returns_none_and_prints_when_editor_missing(monkeypatch, capsys):
    reg = load_registry("male", MARKERS_PATH)
    p = payload()

    def fake_call(args):
        raise FileNotFoundError("no such editor")

    monkeypatch.setattr("tri_wellness.cli.subprocess.call", fake_call)
    edit = make_editor(reg)
    result = await edit(p)
    assert result is None
    assert "could not run editor" in capsys.readouterr().out


def test_ingest_checkpointer_missing_exits_2(monkeypatch, tiny_pdf):
    from tri_wellness.config import get_wellness_settings

    get_wellness_settings.cache_clear()
    monkeypatch.setenv("TRI_ATHLETE_SEX", "male")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr("tri_wellness.graph.checkpointer.checkpointer_ready", lambda url: False)
    result = runner.invoke(app, ["ingest", str(tiny_pdf)])
    get_wellness_settings.cache_clear()
    assert result.exit_code == 2
    assert "checkpoint tables are missing" in result.output


def test_help_lists_panels():
    result = runner.invoke(app, ["--help"])
    assert "panels" in result.output


def test_help_lists_report_and_chat():
    result = runner.invoke(app, ["--help"])
    assert "report" in result.output and "chat" in result.output


def test_help_lists_eval():
    result = runner.invoke(app, ["--help"])
    assert "eval" in result.output
