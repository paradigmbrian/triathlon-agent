from typer.testing import CliRunner

from tri_wellness.cli import app

runner = CliRunner()


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
