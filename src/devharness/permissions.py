"""Permission rules for agent tool invocations.

Returns "allow", "deny", or "ask" for each tool call based on the
command/path. The sandbox decides what is *possible*; these rules only
decide what is worth interrupting the user for - so read-only commands
run silently, and the risky ones still stop and ask.
"""

import os
import re
from fnmatch import fnmatchcase
from pathlib import Path

__all__ = ["check", "decide", "inside_project", "get_project_root"]


def get_project_root():
    """Return the resolved project root, re-evaluated on each call.

    Reads DEV_HARNESS_PROJECT_ROOT if set, otherwise falls back to the
    current working directory. Re-evaluated every call so os.chdir()
    or a later env-var change takes effect.
    """
    root = os.environ.get("DEV_HARNESS_PROJECT_ROOT")
    return Path(root).resolve() if root else Path.cwd().resolve()


# ---------------------------------------------------------------------------
# Bash / shell command rules
# ---------------------------------------------------------------------------
# Last matching rule wins, so put the catch-all first.
BASH_RULES = {
    "*": "ask",
    # --- read-only: let them through ---
    "ls*": "allow", "dir*": "allow",
    "pwd": "allow",
    "cd *": "allow",
    "echo *": "allow",
    "sort*": "allow", "uniq*": "allow", "cut *": "allow",
    "basename *": "allow", "dirname *": "allow",
    "date*": "allow", "time*": "allow",
    "env": "allow", "set": "allow",
    "cat *": "allow", "type *": "allow",
    "head *": "allow", "tail *": "allow", "more *": "allow",
    "wc *": "allow", "file *": "allow",
    "which *": "allow", "where *": "allow",
    "grep *": "allow", "rg *": "allow",
    "find *": "allow", "findstr *": "allow",
    "tree*": "allow",
    "git status*": "allow", "git diff*": "allow",
    "git log*": "allow", "git show*": "allow",
    "git ls-files*": "allow",
    "pytest*": "allow", "python -m pytest*": "allow",
    # --- risky (Linux/macOS): never, even if the user says yes ---
    "rm *": "deny",
    "sudo *": "deny",
    "chmod *": "deny",
    "chown *": "deny",
    "curl *": "deny",
    "wget *": "deny",
    "git push*": "deny", "git reset*": "deny", "git clean*": "deny",
    "mv *": "deny", "cp *": "deny",
    "mkdir *": "deny", "touch *": "deny",
    "pip *": "deny", "pip3 *": "deny",
    "npm *": "deny", "npx *": "deny",
    "uv *": "deny", "poetry *": "deny",
    "kill *": "deny", "pkill *": "deny", "killall *": "deny",
    "reboot*": "deny", "shutdown *": "deny", "halt*": "deny",
    # --- risky (Windows): never, even if the user says yes ---
    "del *": "deny", "erase *": "deny",
    "rmdir *": "deny", "rd *": "deny",
    "move *": "deny", "ren *": "deny", "rename *": "deny",
    "copy *": "deny", "xcopy *": "deny", "robocopy *": "deny",
    "md *": "deny",
    "format *": "deny", "diskpart*": "deny",
    "takeown *": "deny",
    "icacls *": "deny", "cacls *": "deny",   # cacls deprecated but harmless
    "attrib *": "deny",
    "reg *": "deny", "regedit*": "deny",
    "net *": "deny",
    "shutdown *": "deny",
    "taskkill *": "deny", "stop-process*": "deny",
    "sc *": "deny", "schtasks *": "deny",
    "start *": "deny",
    "powershell*": "deny", "pwsh*": "deny",
    "cmd /c*": "deny", "cmd.exe*": "deny",
    "invoke-webrequest*": "deny", "iwr *": "deny",
    "invoke-expression*": "deny", "iex *": "deny",
    "remove-item*": "deny",
    "wmic*": "deny",
    "certutil *": "deny",
    "bitsadmin *": "deny",
}

SEPARATORS = re.compile(r"&&|\|\||;|\||&")

# Sensitive file patterns that should never be written by the agent.
SENSITIVE_EXTENSIONS = {".bat", ".cmd", ".ps1", ".vbs", ".wsf", ".scr", ".com", ".pif"}
SENSITIVE_NAMES = {"autorun.inf", "desktop.ini", "hosts"}


def _matches(text, pattern):
    """Case-insensitive glob match that behaves the same on every OS."""
    return fnmatchcase(text.casefold(), pattern.casefold())


def _iter_subcommands(command):
    """Yield sub-commands from a compound shell command.

    Splits on &&, ||, ;, | and & (bash, cmd.exe, and PowerShell). This is a
    heuristic - it does NOT respect quoting, so `echo "a; b"` is split into
    two parts. That is intentional: splitting too aggressively is safer for
    a permission check than splitting too little.
    """
    for part in SEPARATORS.split(command):
        part = part.strip()
        if part:
            yield part


def decide(command):
    """Rate every part of a compound command; the strictest verdict wins."""
    verdicts = []
    for part in _iter_subcommands(command):
        action = "ask"
        for pattern, rule in BASH_RULES.items():
            if _matches(part, pattern):
                action = rule
        verdicts.append(action)

    for strictest in ("deny", "ask"):
        if strictest in verdicts:
            return strictest
    return "allow"


def inside_project(path):
    """Return True iff `path` resolves to something inside the project root.

    Uses Path.relative_to so that C:\\project-extra is NOT considered inside
    C:\\project (a false positive that os.path.commonpath would produce).
    """
    if path is None:
        return False
    try:
        p = Path(path).resolve()
        p.relative_to(get_project_root())
        return True
    except (ValueError, OSError):
        # ValueError: different drive on Windows, or not a subpath
        # OSError:    invalid path, unreachable UNC share, etc.
        return False


def _sensitive_file(path):
    """Return True if the path looks like a sensitive/high-risk file."""
    if not path:
        return False
    p = Path(path)
    return (
        p.suffix.lower() in SENSITIVE_EXTENSIONS
        or p.name.lower() in SENSITIVE_NAMES
    )


def check(name, args):
    """Return (action, reason). Action is 'allow', 'ask' or 'deny'.

    Guards against missing keys in `args` so an incomplete tool call cannot
    crash the agent loop.
    """
    if name == "bash":
        command = args.get("command")
        if not command:
            return "deny", "bash called without a 'command' argument"
        return decide(command), f"run: {command}"

    if name in ("write_file", "str_replace"):
        path = args.get("path")
        if not path:
            return "deny", f"{name} called without a 'path' argument"
        if _sensitive_file(path):
            return "deny", f"sensitive file type: {path}"
        if not inside_project(path):
            return "ask", f"{name} outside {get_project_root()}: {path}"

    # read_file and any other read-only tools are allowed by default.
    return "allow", None