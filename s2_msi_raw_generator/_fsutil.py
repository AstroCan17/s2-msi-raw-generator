"""Filesystem helpers shared by the pipeline driver and the tests."""

from __future__ import annotations

import zipfile
from pathlib import Path


def zip_dir(src: Path, dest: Path, *, base: str = "self") -> None:
    """Deflate every file under ``src`` into the zip ``dest``.

    ``base`` selects the archive-name root:

    * ``"self"`` — names are relative to ``src`` itself, so a ``.zarr`` directory's ``.zattrs`` lands
      at the zip root (the layout ``zarr``'s ``ZipStore`` opens as a group root).
    * ``"parent"`` — names are relative to ``src.parent``, keeping the top-level directory name in the
      archive (the PSFD ``.zarr.zip`` / ``dir.zip`` publish layout).
    """
    root = src if base == "self" else src.parent
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(src.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(root))
