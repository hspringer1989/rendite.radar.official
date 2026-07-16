from src.models import Word
from src.render.subtitles import build_ass, chunk_words


def _words(*texts, step=0.4):
    return [Word(text=t, start=i * step, end=(i + 1) * step) for i, t in enumerate(texts)]


def test_chunks_capped_at_three_words():
    chunks = chunk_words(_words("eins", "zwei", "drei", "vier", "fünf"))
    assert [len(c) for c in chunks] == [3, 2]


def test_chunks_break_at_punctuation():
    chunks = chunk_words(_words("Hallo.", "Welt", "geht", "so."))
    assert [c[0].text for c in chunks] == ["Hallo.", "Welt"]


def test_ass_file_contains_karaoke_dialogue(tmp_path):
    out = build_ass(_words("Geld", "sparen", "jetzt!"), tmp_path / "subs.ass")
    content = out.read_text(encoding="utf-8-sig")
    assert "[Events]" in content
    assert content.count("Dialogue:") == 1
    assert "\\k40" in content  # 0.4 s per word = 40 centiseconds
    assert "Geld" in content


def test_braces_escaped(tmp_path):
    out = build_ass(_words("{evil}"), tmp_path / "subs.ass")
    assert "{evil}" not in out.read_text(encoding="utf-8-sig")
