"""Tools Sevanya can use.

The rule that makes this a *teaching* assistant rather than a code vending
machine lives here, not in the prompt: there is no write_file and no edit_file.
Sevanya can look at your code and run things, but it physically cannot type for
you. A prompt telling it to hold back can be argued with at 1am. A tool that
doesn't exist cannot.
"""

from pathlib import Path

# Everything is resolved relative to wherever you launch Sevanya from.
PROJECT_ROOT = Path.cwd().resolve()

# How much of a file to hand back before truncating. Files are cheap to read
# but every character costs context window, so cap it.
MAX_CHARS = 40_000


# --- Tool schemas -----------------------------------------------------------
#
# This is what the model actually sees. It never sees your Python functions.
# The `description` is doing real work: it is the only thing telling the model
# *when* reaching for this tool is the right move, so it's worth writing
# carefully. Be prescriptive about the trigger, not just the mechanics.

TOOLS = [
    {
        "name": "read_file",
        "description": (
            "Read a text file from the user's project. Use this whenever the "
            "user mentions a file, or before explaining anything about their "
            "code — read what they actually wrote instead of assuming."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path relative to the project root, e.g. 'sevanya/agent.py'",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_files",
        "description": (
            "List the contents of a directory in the user's project. Use this "
            "to orient yourself before guessing at filenames."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory relative to the project root. Omit for the root itself.",
                }
            },
            "required": [],
        },
    },
]


# --- Implementations --------------------------------------------------------


def _resolve(path_str: str) -> Path:
    """Resolve a model-supplied path, refusing anything outside the project.

    Treat every path from the model as untrusted input. Without this check,
    '../../.ssh/id_rsa' is a perfectly valid thing for it to ask for, and a
    file it reads is a file that ends up in the transcript.

    .resolve() collapses '..' and follows symlinks, so the containment check
    below happens on the real destination rather than the string you were
    handed.
    """
    candidate = (PROJECT_ROOT / path_str).resolve()
    if candidate != PROJECT_ROOT and not candidate.is_relative_to(PROJECT_ROOT):
        raise ValueError(f"path escapes the project root: {path_str!r}")
    return candidate


def read_file(path: str) -> str:
    target = _resolve(path)
    if not target.exists():
        raise FileNotFoundError(f"no such file: {path}")
    if target.is_dir():
        raise IsADirectoryError(f"{path} is a directory — use list_files")

    text = target.read_text(encoding="utf-8", errors="replace")
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + f"\n\n[truncated at {MAX_CHARS} characters]"
    return text


def list_files(path: str = ".") -> str:
    target = _resolve(path)
    if not target.is_dir():
        raise NotADirectoryError(f"{path} is not a directory")

    entries = []
    for child in sorted(target.iterdir()):
        if child.name.startswith(".") or child.name == "__pycache__":
            continue
        entries.append(f"{child.name}/" if child.is_dir() else child.name)

    return "\n".join(entries) if entries else "(empty)"


# Maps the name the model uses to the function we actually call.
REGISTRY = {
    "read_file": read_file,
    "list_files": list_files,
}


def dispatch(name: str, arguments: dict) -> tuple[str, bool]:
    """Run one tool call. Returns (result_text, is_error).

    Errors are caught and returned as text rather than raised. That's
    deliberate: the model can read "no such file: agnet.py", notice the typo,
    and try again. An exception that kills the process teaches it nothing.
    """
    func = REGISTRY.get(name)
    if func is None:
        return f"unknown tool: {name}", True
    try:
        return func(**arguments), False
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}", True
