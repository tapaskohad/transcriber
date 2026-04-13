"""App launcher shared by run.py and package entrypoint."""

from __future__ import annotations


def main() -> None:
    # Use the browser UI as the default visual experience.
    from .web_ui import main as web_main

    web_main()
