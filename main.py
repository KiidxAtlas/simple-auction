"""Launch this checkout from source, or the bundled PyInstaller application."""

import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))


def main() -> int:
    from simple_auction.__main__ import main as run_app

    return run_app()


if __name__ == "__main__":
    sys.exit(main())
