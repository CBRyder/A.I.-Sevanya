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
    {
        "name": "remember",
        "description": (
            "Record something worth carrying into future sessions: a concept "
            "the user just got, a mistake they've now made twice, a project "
            "they're working on, a preference they stated. Write the note for "
            "your future self — enough context to be useful in three weeks. "
            "Use this sparingly and only for things that will still matter "
            "later; a log of everything is a log of nothing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Short tag for searching later, e.g. 'python/decorators' or 'project/sevanya'",
                },
                "note": {
                    "type": "string",
                    "description": "What happened and why it's worth remembering.",
                },
            },
            "required": ["topic", "note"],
        },
    },
    {
        "name": "recall",
        "description": (
            "Search everything from previous sessions — both your journal "
            "notes and the text of past conversations. Use this whenever the "
            "user refers to something as though you should already know it "
            "('that bug from yesterday', 'the thing we tried'), or before "
            "explaining a concept from scratch, since they may have already "
            "covered it with you. Try a couple of different search terms "
            "before concluding there's nothing there — matching is literal, "
            "so the word they just used may not be the word they used then."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A distinctive word or phrase to match. Prefer specific terms over common ones.",
                }
            },
            "required": ["query"],
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


# --- journal tools ----------------------------------------------------------
#
# Note that these *do* write — but they write Sevanya's own notes, never your
# source. The no-writing-your-code rule is intact.


def remember(topic: str, note: str, *, store, conversation_id) -> str:
    store.remember(topic, note, conversation_id)
    return f"noted under '{topic}'"


def recall(query: str, *, store, conversation_id) -> str:
    """Search the journal and past conversations together.

    One tool rather than two, so the model never has to guess which kind of
    memory a question belongs to. Journal notes come first — they're curated,
    so they're higher signal than raw transcript.
    """
    notes = store.recall(query)
    hits = store.search_messages(query)

    if not notes and not hits:
        # Say plainly that nothing was found. A vague answer here invites the
        # model to fill the gap with a plausible guess, which is the exact
        # failure we want: better to come back and ask what was meant.
        return (
            f"No journal notes or past messages match {query!r}. "
            f"Either it wasn't discussed, or it was described differently — "
            f"try another term, or ask the user what they're referring to."
        )

    out = []
    if notes:
        out.append("Journal notes:")
        out += [f"  [{r['created_at']}] {r['topic']}: {r['note']}" for r in notes]
    if hits:
        out.append("From past conversations:")
        for h in hits:
            title = h["title"] or f"conversation {h['conversation_id']}"
            out.append(f"  [{h['when']}] {h['role']} in '{title}': {h['excerpt']}")
    return "\n".join(out)


# Maps the name the model uses to the function we actually call.
REGISTRY = {
    "read_file": read_file,
    "list_files": list_files,
    "remember": remember,
    "recall": recall,
}

# Tools needing access to the journal. Listed explicitly rather than inspected
# at runtime — you can see at a glance which tools touch persistent state.
NEEDS_STORE = {"remember", "recall"}


def dispatch(name: str, arguments: dict, *, store=None, conversation_id=None) -> tuple[str, bool]:
    """Run one tool call. Returns (result_text, is_error).

    Errors are caught and returned as text rather than raised. That's
    deliberate: the model can read "no such file: agnet.py", notice the typo,
    and try again. An exception that kills the process teaches it nothing.
    """
    func = REGISTRY.get(name)
    if func is None:
        return f"unknown tool: {name}", True

    extra = {}
    if name in NEEDS_STORE:
        if store is None:
            return f"{name} is unavailable (no journal in this session)", True
        extra = {"store": store, "conversation_id": conversation_id}

    try:
        return func(**arguments, **extra), False
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}", True
