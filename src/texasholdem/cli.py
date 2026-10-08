"""Compatibility entry point; the CLI lives under interfaces."""
from .interfaces.cli import build_parser, main

__all__ = ["build_parser", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
