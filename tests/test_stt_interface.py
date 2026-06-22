"""The STT interface advertises the per-word `words` field on `speech` (CI-runnable)."""

from named_pipes.interfaces.stt import STT


def test_speech_event_has_words_field():
    speech = next(e for e in STT.events if e.name == "speech")
    field_names = {f.name for f in speech.fields}
    assert "words" in field_names
    words = next(f for f in speech.fields if f.name == "words")
    assert words.type == "list"
    assert words.required is False
