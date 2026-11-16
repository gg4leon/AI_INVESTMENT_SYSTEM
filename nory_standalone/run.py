"""Windows/VS Code entry point; also works when launched from this directory."""

from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nory_standalone.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
