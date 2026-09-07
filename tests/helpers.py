"""Shared test helpers."""

import shutil
import tempfile
from pathlib import Path


class TempProject:
    """Create a temporary directory with helper methods to build fixtures."""

    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="foldchrono_test_"))

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, rel: str, content: str = "hello") -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def remove(self, rel: str) -> None:
        p = self.root / rel
        if p.exists():
            p.unlink()

    def __enter__(self) -> "TempProject":
        return self

    def __exit__(self, *exc) -> None:
        self.cleanup()
