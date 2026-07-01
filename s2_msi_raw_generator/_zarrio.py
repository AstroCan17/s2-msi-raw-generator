# Copyright 2026 Can Deniz Kaya
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Minimal zarr **v2 / v3 write** compatibility.

The generator writes all products in the zarr **v2 on-disk format** (the format ``eopf`` /
``msi-processor`` read). The *Python API* to do so differs between zarr major versions:

* **zarr 3** (local dev + CI): ``open_group(..., zarr_format=2)`` + ``Group.create_array(...)``.
* **zarr 2.18** (the ``eopf==2.8.1`` SDE environment): ``open_group(...)`` (v2 by default) +
  ``Group.create_dataset(data=...)``.

This shim lets the same generator code run in **either** environment, so the L0→L1B end-to-end can run
in a single venv alongside the processor (no separate zarr-3 venv needed).
"""

from __future__ import annotations

import numpy as np
import zarr

# zarr major version (3 on local/CI, 2 in the eopf==2.8.1 SDE env).
ZARR_MAJOR = int(zarr.__version__.split(".")[0])
_V3 = ZARR_MAJOR >= 3


def open_group_w(path):
    """Open a group for writing, forcing the zarr **v2** on-disk format (eopf/msi-processor interop)."""
    if _V3:
        return zarr.open_group(str(path), mode="w", zarr_format=2)
    return zarr.open_group(str(path), mode="w")  # zarr 2 writes v2 by default


def put_array(group, name: str, data, *, dtype=None):
    """Create ``group/name`` from ``data`` (zarr v2/v3 compatible; supports 0-d scalars).

    One chunk per array (the generator's arrays are small, per-band/per-frame). Returns the array.
    """
    a = np.asarray(data)
    if dtype is not None:
        a = a.astype(dtype)
    if _V3:
        z = group.create_array(name, shape=a.shape, dtype=a.dtype, chunks=(a.shape if a.ndim else ()))
        z[...] = a
    else:  # zarr 2: create_dataset infers shape/chunks/dtype from the data
        z = group.create_dataset(name, data=a, overwrite=True)
    return z
