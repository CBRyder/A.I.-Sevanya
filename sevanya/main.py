"""Terminal REPL.

    python -m sevanya.main           resume the most recent conversation
    python -m sevanya.main --new     start a fresh one
    python -m sevanya.main --list    show recent conversations
    python -m sevanya.main --id 7    resume a specific one
"""

import argparse
import sys

from .agent import Agent
from .store import DB_PATH, Store
from .tools import PROJECT_ROOT


def main() -> int:
    parser = argparse.ArgumentParser(prog="sevanya")
    parser.add_argument("--new", action="store_true", help="start a new conversation")
    parser.add_argument("--list", action="store_true", help="list conversations and exit")
    parser.add_argument("--id", type=int, help="resume a specific conversation")
    args = parser.parse_args()

    store = Store()

    if args.list:
        for row in store.list_conversations():
            title = row["title"] or "(untitled)"
            print(f"{row['id']:>4}  {row['updated_at']}  {row['n']:>3} msgs  {title}")
        return 0

    if args.new:
        conversation_id = store.new_conversation()
    elif args.id is not None:
        conversation_id = args.id
    else:
        conversation_id = store.latest_conversation() or store.new_conversation()

    agent = Agent(store, conversation_id)

    print(f"Sevanya — conversation {conversation_id}, reading from {PROJECT_ROOT}")
    print(f"memory: {DB_PATH}")
    if agent.messages:
        print(f"resumed with {len(agent.messages)} messages of history")
    print("ctrl-c or 'exit' to quit\n")

    # First user message doubles as the conversation title, so `--list` is
    # readable instead of a wall of "(untitled)".
    needs_title = not agent.messages

    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not user_input:
            continue
        if user_input in {"exit", "quit"}:
            return 0

        if needs_title:
            store.set_title(conversation_id, user_input[:60])
            needs_title = False

        try:
            reply = agent.send(user_input)
        except Exception as exc:
            # Keep the session alive on a transient API failure — losing the
            # whole conversation to one network blip is infuriating. The
            # transcript is already on disk, so nothing is lost either way.
            print(f"\n[error: {type(exc).__name__}: {exc}]\n", file=sys.stderr)
            continue

        print(f"\nsevanya> {reply}\n")


if __name__ == "__main__":
    raise SystemExit(main())
