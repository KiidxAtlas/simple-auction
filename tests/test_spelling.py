"""The spellchecker is local and usable without a QApplication or network."""

import json

import pytest

from simple_auction.services import spelling, storage
from simple_auction.services.spelling import Spelling, word_spans


@pytest.fixture
def engine(tmp_path):
    return Spelling(tmp_path / "spelling.json")


def test_english_and_auction_words_are_correct(engine):
    for word in (
        "description",
        "excellent",
        "rifling",
        "bluing",
        "consignor",
        "Glock",
        "Mauser",
        "Wesson",
        "CZ",
        "CAN",
        "can't",
        "can’t",
        "rifle’s",
    ):
        assert engine.correct(word), word
    assert not engine.correct("MISPELLED")
    assert not engine.correct("mispelled")


def test_suggestions_are_bounded_deterministic_and_keep_case(engine):
    suggestions = engine.suggest("mispelled")
    assert "misspelled" in suggestions
    assert 0 < len(suggestions) <= 8
    assert suggestions == engine.suggest("mispelled")
    assert engine.suggest("MISPELLED") == [word.upper() for word in suggestions]
    assert engine.suggest("Mispelled") == [word.capitalize() for word in suggestions]
    assert engine.suggest("rifle") == []
    assert engine.suggest("x" * 1000) == []
    # Callers cannot mutate the cached suggestions.
    suggestions.clear()
    assert engine.suggest("mispelled")


def test_ignore_is_case_insensitive_session_only_and_invalidates_cache(engine):
    assert not engine.correct("flibberty")
    assert engine.suggest("flibberty") is not None
    before = engine.revision
    engine.ignore("FLIBBERTY")
    assert engine.revision == before + 1
    assert engine.correct("Flibberty")
    assert engine.suggest("flibberty") == []
    engine.ignore("flibberty")
    assert engine.revision == before + 1
    assert not engine.path.exists()
    assert not Spelling(engine.path).correct("flibberty")


def test_add_persists_case_insensitively_and_preserves_other_data(engine):
    engine.path.write_text(json.dumps({"words": ["Zorblax"], "metadata": {"a": 1}}))
    assert not engine.correct("flibberty")
    engine.add("FLIBBERTY")
    assert engine.correct("Flibberty")
    assert engine.correct("zorblax")
    assert engine.revision == 1
    assert json.loads(engine.path.read_text()) == {
        "words": ["flibberty", "zorblax"],
        "metadata": {"a": 1},
    }
    engine.add("Flibberty")
    assert engine.revision == 1
    restored = Spelling(engine.path)
    assert restored.correct("FLIBBERTY")
    assert restored.correct("zorblax")


def test_multiple_instances_merge_personal_words(tmp_path):
    path = tmp_path / "spelling.json"
    first, second = Spelling(path), Spelling(path)
    first.add("flibberty")
    second.add("zorblax")
    restored = Spelling(path)
    assert restored.correct("flibberty")
    assert restored.correct("zorblax")


@pytest.mark.parametrize("raw", [b"{broken", b"[]", b"{}", b'{"words": [42]}', b"\xff"])
def test_damaged_dictionary_still_checks_but_cannot_be_overwritten(tmp_path, raw):
    path = tmp_path / "spelling.json"
    path.write_bytes(raw)
    engine = Spelling(path)
    assert engine.correct("rifle")
    with pytest.raises(ValueError):
        engine.add("flibberty")
    assert path.read_bytes() == raw
    assert engine.revision == 0
    assert not engine.correct("flibberty")


def test_failed_commit_does_not_claim_success_or_change_session(engine, monkeypatch):
    engine.add("zorblax")
    previous = engine.path.read_bytes()
    revision = engine.revision

    def fail(path, data):
        raise OSError("disk full")

    monkeypatch.setattr(storage, "atomic_write", fail)
    with pytest.raises(OSError, match="disk full"):
        engine.add("flibberty")
    assert engine.revision == revision
    assert engine.path.read_bytes() == previous
    assert not engine.correct("flibberty")


def test_atomic_replace_failure_preserves_dictionary(engine, monkeypatch):
    engine.add("zorblax")
    previous = engine.path.read_bytes()

    def fail(*args):
        raise OSError("cannot replace")

    monkeypatch.setattr(storage.os, "replace", fail)
    with pytest.raises(OSError, match="cannot replace"):
        engine.add("flibberty")
    assert engine.path.read_bytes() == previous
    assert not list(engine.path.parent.glob(".spelling.json-*"))
    assert not engine.correct("flibberty")


@pytest.mark.parametrize(
    "word", ["", "two words", "AB123", "http://example.com", "user_name"]
)
def test_add_rejects_nonwords_without_writing(engine, word):
    with pytest.raises(ValueError):
        engine.add(word)
    assert not engine.path.exists()
    assert engine.revision == 0


def test_word_spans_keep_unicode_apostrophes_and_python_offsets():
    text = "🔫 Café rifle’s can't MISPELLED, well-made."
    spans = word_spans(text)
    assert [word for _, _, word in spans] == [
        "Café",
        "rifle’s",
        "can't",
        "MISPELLED",
        "well",
        "made",
    ]
    assert spans[0] == (2, 6, "Café")
    for start, end, word in spans:
        assert text[start:end] == word


def test_word_spans_skip_identifiers_and_addresses_as_whole_tokens():
    text = (
        "Good AB123 123AB AK-47 .308 9mm 12/34 2024-05-02 foo_bar "
        "https://example.com/mispelled www.example.com "
        "name.surname+lot@example.com badword."
    )
    assert [word for _, _, word in word_spans(text)] == ["Good", "badword"]


def test_default_path_is_config_sibling(_isolated_home):
    assert (
        Spelling().path
        == _isolated_home / ".config" / "simple-auction" / "spelling.json"
    )


def test_caches_are_bounded(engine, monkeypatch):
    monkeypatch.setattr(
        spelling.SpellChecker, "candidates", lambda self, word: {"rifle"}
    )
    for number in range(2200):
        # Alphabetic distinct tokens, so this exercises the spelling caches.
        token = "zz" + chr(0x4E00 + number)
        engine.correct(token)
        engine.suggest(token)
    assert len(engine._checks) <= 2048
    assert len(engine._suggestions) <= 256
    engine.ignore("zzword")
    assert not engine._checks
    assert not engine._suggestions


def test_common_makers_seed_is_local():
    assert "network" not in spelling.__dict__
    assert "Config" not in spelling.__dict__
