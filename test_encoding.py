"""Tests for encoding safety across tools.py, session.py, context.py.

These guard against the Windows locale-encoding bugs we hit:
- UnicodeDecodeError from subprocess pipes (cp1252 default)
- TypeError from result.stdout being None after a decode failure
- mojibake / crashes when reading or writing UTF-8 files
"""

import sys
from pathlib import Path

import pytest

from tools import bash, read_file, write_file


UTF8_SAMPLE = "سلام 🎉\nnaïve café\n日本語\nÑoño"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def utf8_file(tmp_path: Path) -> Path:
    """A UTF-8 file containing non-ASCII text and an emoji."""
    p = tmp_path / "sample.txt"
    p.write_text(UTF8_SAMPLE, encoding="utf-8")
    return p


@pytest.fixture
def isolated_session(tmp_path: Path, monkeypatch):
    """Isolate session.py to a temp dir and reset the WRITTEN global."""
    import session

    monkeypatch.setattr(session, "SESSION_DIR", tmp_path)
    monkeypatch.setattr(session, "WRITTEN", 0)
    return session


# ---------------------------------------------------------------------------
# bash() — subprocess path
# ---------------------------------------------------------------------------

class TestBash:
    def test_simple_command(self):
        assert "hello" in bash("echo hello")

    def test_returns_string_never_none(self):
        """Regression: result.stdout could be None and crash `stdout + stderr`."""
        out = bash("echo test")
        assert isinstance(out, str)

    def test_no_output_falls_back_to_placeholder(self):
        """A command with no output should return the placeholder, not empty str."""
        assert bash("cd .") == "(no output)"

    def test_reads_utf8_file_via_subprocess(self, utf8_file: Path):
        """The original crash: `type <file>` on a UTF-8 file with non-ASCII bytes."""
        out = bash(f'type "{utf8_file}"')
        assert "café" in out
        assert "日本語" in out

    def test_failing_command_still_returns_string(self):
        out = bash("this_command_does_not_exist_xyz")
        assert isinstance(out, str)
        assert out  # truthy — either error message or "(no output)"

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only shell syntax")
    def test_stderr_is_captured_windows(self):
        out = bash("dir nonexistent_dir_xyz")
        assert isinstance(out, str)
        assert out

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only shell syntax")
    def test_windows_cmd_syntax(self, utf8_file: Path):
        out = bash(f'type "{utf8_file}"')
        assert "café" in out


# ---------------------------------------------------------------------------
# read_file() / write_file() — open() path
# ---------------------------------------------------------------------------

class TestFileIO:
    def test_write_then_read_roundtrip(self, tmp_path: Path):
        target = tmp_path / "roundtrip.txt"
        write_file(str(target), UTF8_SAMPLE)
        assert read_file(str(target)) == UTF8_SAMPLE

    def test_write_creates_utf8_bytes(self, tmp_path: Path):
        target = tmp_path / "bytes.txt"
        write_file(str(target), "café")
        assert target.read_bytes() == "café".encode("utf-8")

    def test_read_utf8_file_directly(self, utf8_file: Path):
        assert read_file(str(utf8_file)) == UTF8_SAMPLE

    def test_emoji_survives_roundtrip(self, tmp_path: Path):
        target = tmp_path / "emoji.txt"
        write_file(str(target), "🎉🚀✨")
        assert read_file(str(target)) == "🎉🚀✨"

    def test_farsi_survives_roundtrip(self, tmp_path: Path):
        target = tmp_path / "farsi.txt"
        write_file(str(target), "سلام دنیا")
        assert read_file(str(target)) == "سلام دنیا"


# ---------------------------------------------------------------------------
# session.py — JSONL persistence
# ---------------------------------------------------------------------------

class TestSession:
    def test_message_with_emoji_survives_roundtrip(self, isolated_session):
        session = isolated_session
        session.save([{"role": "user", "content": "سلام 🎉"}])

        files = list(session.SESSION_DIR.glob("*.jsonl"))
        assert files, "session.save should have written a JSONL file"

        # Raw bytes must be valid UTF-8
        files[0].read_bytes().decode("utf-8")

    def test_load_returns_original_content(self, isolated_session):
        session = isolated_session
        original = {"role": "assistant", "content": "café ☕ 日本語"}
        session.save([original])

        loaded = session.load(session.CURRENT)
        assert loaded
        assert loaded[-1]["content"] == original["content"]


# ---------------------------------------------------------------------------
# context.py — reminder() must not crash on non-ASCII git output
# ---------------------------------------------------------------------------

class TestContext:
    def test_reminder_returns_dict(self, monkeypatch):
        monkeypatch.setattr(
            "context.git",
            lambda cmd: "main" if "branch" in cmd else "",
        )
        from context import reminder

        r = reminder()
        assert isinstance(r, dict)
        assert "role" in r
        assert "content" in r

    def test_reminder_content_is_string(self, monkeypatch):
        monkeypatch.setattr(
            "context.git",
            lambda cmd: "main" if "branch" in cmd else "",
        )
        from context import reminder

        r = reminder()
        assert isinstance(r["content"], str)
        assert r["content"]  # non-empty