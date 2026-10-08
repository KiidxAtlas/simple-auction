"""Entry point for standalone (PyInstaller) builds; also runs with `python main.py`."""

import sys

from simple_auction.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
