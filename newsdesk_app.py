#!/usr/bin/env python3
"""Launcher for the NewsDesk desktop app (equivalent to ``python -m newsdesk``)."""

from newsdesk.app import main

if __name__ == "__main__":
    raise SystemExit(main())
