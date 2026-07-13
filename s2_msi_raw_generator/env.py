"""Environment configuration — single source of truth from ``.env``.

All pipeline scripts load the repository ``.env`` at startup. Required path variables must be
set; there are no silent fallbacks to ``~/data-store`` or baked-in defaults.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

_REQUIRED_PATHS = (
    "S2_L1B_INPUT",
    "S2_L0_INPUT",
    "S2_GIPP_DIR",
    "S2_AUX_DIR",
    "OUTPUT_DIR",
)


def load_dotenv(path: Path | None = None) -> None:
    """Load ``KEY=VALUE`` lines from ``.env`` into ``os.environ`` (does not override existing)."""
    env_file = path or (_REPO_ROOT / ".env")
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


def _get(name: str, required: bool = False) -> str | None:
    val = os.environ.get(name)
    if required and not val:
        raise SystemExit(f"missing required environment variable {name} (set in .env)")
    return val


def require_paths() -> None:
    """Exit if any mandatory path variable is unset."""
    missing = [k for k in _REQUIRED_PATHS if not os.environ.get(k)]
    if missing:
        raise SystemExit(
            "missing required .env variables: "
            + ", ".join(missing)
            + f" — copy {_REPO_ROOT / '.env.example'} to .env and fill paths"
        )


def init_env(*, require: bool = False) -> None:
    """Load ``.env`` and optionally enforce required path variables."""
    load_dotenv()
    if require:
        require_paths()


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


def l1b_input() -> Path:
    return Path(_get("S2_L1B_INPUT", required=True)).expanduser()


def l0_input() -> Path:
    return Path(_get("S2_L0_INPUT", required=True)).expanduser()


def gipp_dir() -> Path:
    return Path(_get("S2_GIPP_DIR", required=True)).expanduser()


def aux_dir() -> Path:
    return Path(_get("S2_AUX_DIR", required=True)).expanduser()


def output_dir() -> Path:
    return Path(_get("OUTPUT_DIR", required=True)).expanduser()


def adf_eopf_dir() -> Path:
    return aux_dir() / "adf-eopf"


def framing_dir() -> Path:
    return aux_dir() / "framing"


def store_paths() -> dict[str, Path]:
    """Pipeline store layout under ``OUTPUT_DIR``."""
    root = output_dir()
    paths = {
        "root": root,
        "inputs": root / "inputs",
        "caldb": root / "caldb",
        "l1a": root / "l1a",
        "l0": root / "l0",
        "l1a_prime": root / "l1a_prime",
        "l1b": root / "l1b",
        "quicklook": root / "quicklook",
        "figures": root / "figures",
        "report": root / "report",
    }
    for d in paths.values():
        d.mkdir(parents=True, exist_ok=True)
    return paths


def find_adf_eopf(adf_type: str) -> str | None:
    """First ``S0*_ADF_<adf_type>_*.json`` under ``{S2_AUX_DIR}/adf-eopf``."""
    import glob

    d = adf_eopf_dir()
    if not d.is_dir():
        return None
    hits = sorted(glob.glob(str(d / f"S0*_ADF_{adf_type}_*.json")))
    return hits[0] if hits else None


def find_framing_table() -> Path | None:
    """First ``framing_lines_*.json`` under ``{S2_AUX_DIR}/framing``."""
    d = framing_dir()
    if not d.is_dir():
        return None
    hits = sorted(d.glob("framing_lines_*.json"))
    return hits[0] if hits else None


def ensure_repo_on_path() -> None:
    """Allow ``python scripts/run_pipeline.py`` without a prior ``pip install -e``."""
    root = str(_REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
