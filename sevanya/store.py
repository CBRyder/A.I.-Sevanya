"""Persistence: conversations, messages, and the learning journal.

Two things live in here, and they're different in kind.

The **conversation log** is mechanical — it's what lets you close the terminal
without losing your place, and later it's what lets phone-you and desktop-you
be in the same conversation.

The **journal** is the interesting one. It's what Sevanya has noticed about how
you're learning: what you worked on, where you got stuck, what clicked. That's
the part no off-the-shelf tool can have, because nobody else has your history.
It gets written by Sevanya itself through the `remember` tool, not by a script.
"""

import json
import sqlite3
import threading
from pathlib import Path

# Lives in your home directory, not the project — Sevanya follows you across
# repos, and its memory of you shouldn't reset because you cd'd somewhere else.
DB_PATH = Path.home() / ".sevanya" / "sevanya.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id         INTEGER PRIMARY KEY,
    title      TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,
    -- JSON, because content is not always a string. An assistant turn is a
    -- *list of blocks* that can include tool_use and thinking blocks, and
    -- those have to survive a reload intact. See _jsonable below.
    content         TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, id);

CREATE TABLE IF NOT EXISTS journal (
    id              INTEGER PRIMARY KEY,
    topic           TEXT NOT NULL,
    note            TEXT NOT NULL,
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_journal_topic ON journal(topic);

-- What you've said you're going to do. Distinct from the journal: the journal
-- is what Sevanya noticed about how you're learning, and it's write-once. This
-- is a working list with a lifecycle — added, completed, or dropped when it
-- turns out not to matter.
CREATE TABLE IF NOT EXISTS task_list (
    id              INTEGER PRIMARY KEY,
    task            TEXT NOT NULL,
    done            INTEGER NOT NULL DEFAULT 0,
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_task_list_open ON task_list(done, id);

-- A log of things that happened to Sevanya herself rather than in a
-- conversation: restarts, dependency installs, repos synced, errors. It exists
-- because most of these happen while nobody is looking at the terminal — the
-- whole point is that she runs on the PC and you're on the phone.
CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL,
    message    TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_notifications_id ON notifications(id DESC);
"""


def _jsonable(content):
    """Make message content safe to store as JSON.

    A user turn's content is usually a plain string. An assistant turn's is a
    list of SDK block objects (pydantic models), which json.dumps can't handle.

    This matters more than it looks: if you stored only the *text* of an
    assistant turn, you'd silently drop its tool_use blocks. Reload that
    conversation and your tool_result blocks now answer requests the model
    can't see — and the API rejects the whole thing. Keep the blocks.
    """
    if isinstance(content, str):
        return content
    out = []
    for block in content:
        if hasattr(block, "model_dump"):
            # exclude_none keeps the stored rows clean; the SDK is happy to
            # receive dicts back in place of its own objects.
            out.append(block.model_dump(exclude_none=True))
        else:
            out.append(block)  # already a plain dict (our tool_result blocks)
    return out


def _readable(content) -> str:
    """Pull human text out of stored content, skipping tool plumbing.

    tool_result blocks are deliberately excluded: they hold whole files
    Sevanya read, and matching your search term inside someone's source dump
    is noise, not recall.
    """
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and block.get("text"):
            parts.append(block["text"])
    return "\n".join(parts)


def _window(text: str, query: str, pad: int = 120) -> str | None:
    """A slice of `text` around the first case-insensitive hit on `query`."""
    idx = text.lower().find(query.lower())
    if idx == -1:
        return None
    start, end = max(0, idx - pad), min(len(text), idx + len(query) + pad)
    excerpt = text[start:end].replace("\n", " ").strip()
    return ("…" if start else "") + excerpt + ("…" if end < len(text) else "")


class Store:
    """One SQLite connection per thread.

    SQLite connections are bound to the thread that opened them — hand one to
    another thread and it raises. The terminal REPL is single-threaded so this
    never mattered, but the web server runs each request in a threadpool, so a
    single shared connection breaks the moment two requests overlap.

    `self.db` is a property that hands back this thread's connection, creating
    it on first use. Every method below is unchanged as a result.
    """

    def __init__(self, path: Path = DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._local = threading.local()
        # Create the schema once, on whichever thread built the Store.
        self.db.executescript(SCHEMA)
        self.db.commit()

    @property
    def db(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            # timeout: wait rather than erroring if another thread is mid-write.
            conn = sqlite3.connect(self._path, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            # WAL lets readers work while a writer holds the file.
            conn.execute("PRAGMA journal_mode = WAL")
            self._local.conn = conn
        return conn

    # --- conversations ------------------------------------------------------

    def new_conversation(self, title: str | None = None) -> int:
        cur = self.db.execute("INSERT INTO conversations (title) VALUES (?)", (title,))
        self.db.commit()
        return cur.lastrowid

    def latest_conversation(self) -> int | None:
        row = self.db.execute(
            "SELECT id FROM conversations ORDER BY updated_at DESC, id DESC LIMIT 1"
        ).fetchone()
        return row["id"] if row else None

    def conversation_exists(self, conversation_id: int) -> bool:
        row = self.db.execute(
            "SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        return row is not None

    def list_conversations(self, limit: int = 10) -> list[sqlite3.Row]:
        return self.db.execute(
            """SELECT c.id, c.title, c.updated_at, COUNT(m.id) AS n
               FROM conversations c LEFT JOIN messages m ON m.conversation_id = c.id
               GROUP BY c.id ORDER BY c.updated_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()

    def set_title(self, conversation_id: int, title: str) -> None:
        self.db.execute(
            "UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id)
        )
        self.db.commit()

    # --- messages -----------------------------------------------------------

    def append_message(self, conversation_id: int, role: str, content) -> None:
        self.db.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)",
            (conversation_id, role, json.dumps(_jsonable(content))),
        )
        self.db.execute(
            "UPDATE conversations SET updated_at = datetime('now') WHERE id = ?",
            (conversation_id,),
        )
        self.db.commit()

    def load_messages(self, conversation_id: int) -> list[dict]:
        rows = self.db.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        ).fetchall()
        return [{"role": r["role"], "content": json.loads(r["content"])} for r in rows]

    # --- journal ------------------------------------------------------------

    def remember(self, topic: str, note: str, conversation_id: int | None = None) -> None:
        self.db.execute(
            "INSERT INTO journal (topic, note, conversation_id) VALUES (?, ?, ?)",
            (topic, note, conversation_id),
        )
        self.db.commit()

    def recall(self, query: str, limit: int = 10) -> list[sqlite3.Row]:
        """Substring search over the journal.

        Deliberately dumb. Semantic search over a few hundred short notes
        would be more machinery than it's worth — revisit if LIKE actually
        starts failing you, not before.
        """
        like = f"%{query}%"
        return self.db.execute(
            """SELECT topic, note, created_at FROM journal
               WHERE topic LIKE ? OR note LIKE ?
               ORDER BY created_at DESC LIMIT ?""",
            (like, like, limit),
        ).fetchall()

    def search_messages(self, query: str, limit: int = 6) -> list[dict]:
        """Substring search across past conversations.

        The journal is what Sevanya chose to write down; this is everything
        else. Most of what you'll want to refer back to ("that parser bug")
        never got a journal entry — it's just sitting in a transcript.

        Two filters keep the results useful rather than overwhelming:
        tool_result blocks are skipped (they're full file contents, and
        matching inside them tells you nothing), and each hit is trimmed to a
        window around the match instead of returning the whole message.
        """
        rows = self.db.execute(
            """SELECT m.conversation_id, m.role, m.content, m.created_at,
                      c.title
               FROM messages m JOIN conversations c ON c.id = m.conversation_id
               WHERE m.content LIKE ?
               ORDER BY m.id DESC LIMIT ?""",
            (f"%{query}%", limit * 4),  # over-fetch; filtering drops some
        ).fetchall()

        hits = []
        for row in rows:
            text = _readable(json.loads(row["content"]))
            if not text:
                continue
            window = _window(text, query)
            if window is None:
                continue  # matched only inside JSON scaffolding, not real text
            hits.append(
                {
                    "conversation_id": row["conversation_id"],
                    "title": row["title"],
                    "role": row["role"],
                    "when": row["created_at"],
                    "excerpt": window,
                }
            )
            if len(hits) >= limit:
                break
        return hits

    def recent_journal(self, limit: int = 5) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT topic, note, created_at FROM journal ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()

    # --- the task list ------------------------------------------------------
    #
    # CREATE TABLE IF NOT EXISTS means an existing ~/.sevanya/sevanya.db picks
    # this up the next time Sevanya starts. There's no migration to run.

    def add_task(self, task: str, conversation_id: int | None = None) -> int:
        cur = self.db.execute(
            "INSERT INTO task_list (task, conversation_id) VALUES (?, ?)",
            (task, conversation_id),
        )
        self.db.commit()
        return cur.lastrowid

    def get_task(self, task_id: int) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT id, task, done, created_at, completed_at FROM task_list WHERE id = ?",
            (task_id,),
        ).fetchone()

    def complete_task(self, task_id: int) -> bool:
        """Mark one done. False if there's no such task.

        Completing something already complete is not an error — it's a no-op
        with an honest answer, because the interesting failure is naming a task
        that doesn't exist.
        """
        cur = self.db.execute(
            "UPDATE task_list SET done = 1, completed_at = datetime('now') WHERE id = ?",
            (task_id,),
        )
        self.db.commit()
        return cur.rowcount > 0

    def reopen_task(self, task_id: int) -> bool:
        cur = self.db.execute(
            "UPDATE task_list SET done = 0, completed_at = NULL WHERE id = ?",
            (task_id,),
        )
        self.db.commit()
        return cur.rowcount > 0

    def remove_task(self, task_id: int) -> bool:
        cur = self.db.execute("DELETE FROM task_list WHERE id = ?", (task_id,))
        self.db.commit()
        return cur.rowcount > 0

    def list_tasks(self, include_done: bool = False, limit: int = 50) -> list[sqlite3.Row]:
        """Open tasks oldest first — the order you'd work through them."""
        where = "" if include_done else "WHERE done = 0"
        return self.db.execute(
            f"""SELECT id, task, done, created_at, completed_at FROM task_list
                {where} ORDER BY done, id LIMIT ?""",
            (limit,),
        ).fetchall()

    def open_tasks(self, limit: int = 10) -> list[sqlite3.Row]:
        # Selects `done` as well, even though it's 0 for every row here, so
        # these rows have the same shape as list_tasks' and anything that
        # formats one can format the other. sqlite3.Row raises on a missing
        # column, so a narrower select turns a shared helper into a crash.
        return self.db.execute(
            """SELECT id, task, done, created_at FROM task_list
               WHERE done = 0 ORDER BY id LIMIT ?""",
            (limit,),
        ).fetchall()

    # --- notifications ------------------------------------------------------

    def notify(self, kind: str, message: str) -> int:
        cur = self.db.execute(
            "INSERT INTO notifications (kind, message) VALUES (?, ?)",
            (kind, message),
        )
        self.db.commit()
        return cur.lastrowid

    def notifications(self, limit: int = 200) -> list[sqlite3.Row]:
        """Newest first — this is a log you scroll, not a queue you work."""
        return self.db.execute(
            "SELECT id, kind, message, created_at FROM notifications ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()

    def trim_notifications(self, keep: int = 500) -> int:
        """Drop the oldest once the log gets long.

        Unbounded it would grow forever for something nobody reads twice, and
        it shares a database with the journal, which is the part that matters.
        """
        cur = self.db.execute(
            """DELETE FROM notifications WHERE id NOT IN (
                   SELECT id FROM notifications ORDER BY id DESC LIMIT ?
               )""",
            (keep,),
        )
        self.db.commit()
        return cur.rowcount

    def close(self) -> None:
        """Close this thread's connection. Other threads keep their own."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None
