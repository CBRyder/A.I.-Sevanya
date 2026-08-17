"""Terminal REPL. Run with: python -m sevanya.main"""

import sys

from .agent import Agent
from .tools import PROJECT_ROOT


def main() -> int:
    print(f"Sevanya — reading from {PROJECT_ROOT}")
    print("ctrl-c or 'exit' to quit\n")

    agent = Agent()

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

        try:
            reply = agent.send(user_input)
        except Exception as exc:
            # Keep the session alive on a transient API failure — losing the
            # whole conversation to one network blip is infuriating.
            print(f"\n[error: {type(exc).__name__}: {exc}]\n", file=sys.stderr)
            continue

        print(f"\nsevanya> {reply}\n")


if __name__ == "__main__":
    raise SystemExit(main())
