"""Shared test environment — sets required ``S2_*`` path variables for pipeline driver tests."""

from __future__ import annotations

from pathlib import Path

import pytest


def patch_pipeline_env(monkeypatch, store: Path, **extra: str) -> None:
    """Set ``OUTPUT_DIR`` and mandatory path vars so ``run_pipeline.main(load_env=False)`` runs."""
    store = store.expanduser()
    store.mkdir(parents=True, exist_ok=True)
    dummy = store / "_dummy"
    monkeypatch.setenv("OUTPUT_DIR", str(store))
    monkeypatch.setenv("S2_L1B_INPUT", extra.get("l1b", str(dummy / "l1b.zarr")))
    monkeypatch.setenv("S2_L0_INPUT", extra.get("l0", str(dummy / "l0.zarr")))
    monkeypatch.setenv("S2_GIPP_DIR", extra.get("gipp", str(dummy / "gipp")))
    monkeypatch.setenv("S2_AUX_DIR", extra.get("aux", str(dummy / "aux")))


@pytest.fixture()
def pipeline_store(tmp_path):
    return tmp_path / "store"
