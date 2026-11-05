"""PyInstaller entry point for the windowed GUI exe: absolute imports only."""
import sys

from adfu_tool.gui import run

if __name__ == "__main__":
    smoke = "--smoke" in sys.argv
    sys.exit(run(smoke=smoke))
