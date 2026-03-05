"""Entry point for `python -m agent_context` and the `agent-context` CLI."""

from agent_context.cli.app import app


def main() -> None:
    app()


if __name__ == "__main__":
    main()
