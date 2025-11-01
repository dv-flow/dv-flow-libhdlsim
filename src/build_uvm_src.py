from __future__ import annotations

import tarfile
from pathlib import Path

from setuptools.command.build_py import build_py as _build_py
from setuptools.command.sdist import sdist as _sdist


def _project_root() -> Path:
    # Resolve project root by locating pyproject.toml, works from src/ as well
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    # Fallback: assume src/ layout (this file in src/)
    return Path(__file__).resolve().parents[1]


ROOT = _project_root()
UVM_SRC = ROOT / "packages" / "uvm" / "src"
OUT = ROOT / "src" / "dv_flow" / "libhdlsim" / "share" / "uvm_src.tar.bz2"


def _make_uvm_tarball() -> None:
    if not UVM_SRC.is_dir():
        print(f"[build] Skipping: {UVM_SRC} not found")
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # Always recreate to ensure freshness
    with tarfile.open(OUT, mode="w:bz2") as tf:
        # Put contents under top-level 'src' inside the tarball
        tf.add(UVM_SRC, arcname="src")
    print(f"[build] Wrote {OUT}")


class BuildPy(_build_py):
    def run(self):
        _make_uvm_tarball()
        super().run()


class Sdist(_sdist):
    def run(self):
        _make_uvm_tarball()
        super().run()


__all__ = ["BuildPy", "Sdist"]
