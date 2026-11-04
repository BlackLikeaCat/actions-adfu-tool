"""PyInstaller entry point: absolute imports only."""
import sys

from adfu_tool.cli import main

if __name__ == "__main__":
    sys.exit(main())
