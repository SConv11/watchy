"""Tests for the per-ticker digest store (#28)."""

from watchy.digest_store import load_digest, save_digest


def test_round_trip(tmp_path):
    result = {
        "ticker": "NVDA",
        "verdict": "HOLD",
        "_reports": {"market_report": "table here"},
        "_decision_raw": "FINAL: HOLD",
        "risk_assessment": None,
    }
    save_digest("NVDA", result, digest_dir=str(tmp_path))
    loaded = load_digest("NVDA", digest_dir=str(tmp_path))
    assert loaded is not None
    got, saved_at = loaded
    assert got == result
    assert saved_at is not None


def test_missing_returns_none(tmp_path):
    assert load_digest("ZZZZ", digest_dir=str(tmp_path)) is None


def test_case_insensitive_filename(tmp_path):
    save_digest("nvda", {"ticker": "NVDA"}, digest_dir=str(tmp_path))
    assert load_digest("NVDA", digest_dir=str(tmp_path)) is not None


def test_bad_file_returns_none(tmp_path):
    path = tmp_path / "NVDA_digest.json"
    path.write_text("not json{", encoding="utf-8")
    assert load_digest("NVDA", digest_dir=str(tmp_path)) is None


def test_non_serializable_degrades(tmp_path):
    # default=str keeps a stray object from losing the whole digest
    class Weird:
        def __str__(self):
            return "weird-repr"

    save_digest("NVDA", {"x": Weird()}, digest_dir=str(tmp_path))
    loaded = load_digest("NVDA", digest_dir=str(tmp_path))
    assert loaded is not None
    assert loaded[0]["x"] == "weird-repr"
