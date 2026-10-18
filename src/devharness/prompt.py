"""The input line.

`input()` cannot edit a line that has wrapped past the screen width - the
terminal owns the wrapping and readline cannot see it. prompt_toolkit redraws
the line itself, so deleting, word jumps and history all keep working once the
text is longer than the screen.
"""

import re
from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML, fragment_list_to_text
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.processors import Processor, Transformation
from prompt_toolkit.styles import Style

HISTORY = Path.home() / ".agents" / "history"

STYLE = Style.from_dict({"prompt": "bold #9ece6a"})

_RTL_PATTERN = re.compile(
    r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]"
)

# Disable ligatures so character length stays 1:1 with the input buffer for accurate cursor placement
_prompt_reshaper = arabic_reshaper.ArabicReshaper(
    configuration={
        "delete_harakat": False,
        "support_ligatures": False,
    }
)


def _has_rtl(text: str) -> bool:
    return bool(_RTL_PATTERN.search(text))


def _rtl_line(text: str) -> str:
    if not text or not _has_rtl(text):
        return text
    return str(get_display(_prompt_reshaper.reshape(text)))


class _RTLProcessor(Processor):
    """Render RTL and bidirectional text in real-time without modifying the underlying buffer."""
    
    def apply_transformation(self, transformation_input):
        line_text = fragment_list_to_text(transformation_input.fragments)
        if not _has_rtl(line_text):
            return Transformation(transformation_input.fragments)

        display_text = _rtl_line(line_text)
        n = len(line_text)
        m = len(display_text)

        def source_to_display(pos: int) -> int:
            # Map cursor position for RTL display
            return max(0, min(m, m - pos))

        def display_to_source(pos: int) -> int:
            return max(0, min(n, n - pos))

        return Transformation(
            fragments=[("", display_text)],
            source_to_display=source_to_display,
            display_to_source=display_to_source,
        )


bindings = KeyBindings()


@bindings.add("escape", "left")  # Alt+left
def _word_left(event):
    document = event.current_buffer.document
    event.current_buffer.cursor_position += (
        document.find_previous_word_beginning(count=1) or 0
    )


@bindings.add("escape", "right")  # Alt+right
def _word_right(event):
    document = event.current_buffer.document
    event.current_buffer.cursor_position += (
        document.find_next_word_ending(count=1) or 0
    )


@bindings.add("escape", "enter")  # Alt+Enter
def _newline(event):
    """Option-enter starts a new line instead of sending the message."""
    event.current_buffer.insert_text("\n")


SESSION = None


def read(prompt="> "):
    """Read one message. Raises EOFError on ctrl-d, like input() does."""
    global SESSION
    if SESSION is None:
        HISTORY.parent.mkdir(parents=True, exist_ok=True)
        SESSION = PromptSession(
            history=FileHistory(str(HISTORY)),
            key_bindings=bindings,
            style=STYLE,
            input_processors=[_RTLProcessor()],
        )
    return SESSION.prompt(HTML(f"<prompt>{_rtl_line(prompt)}</prompt>"))