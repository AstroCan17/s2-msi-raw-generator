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

"""Anonymous S3 object fetcher (stdlib only) for retrieving public input products.

A dependency-free helper for pulling Sentinel-2 L1A / L1B granules (or any objects) from a public,
anonymously-readable S3-compatible endpoint — e.g. an open-data bucket — into a local directory,
with listing pagination and per-object integrity verification. It uses only the standard library
(:mod:`urllib.request`, :mod:`xml.etree.ElementTree`, :mod:`hashlib`, :mod:`concurrent.futures`),
in keeping with the project's pure ``numpy`` + stdlib policy, and issues unauthenticated ``GET``
requests only (no credentials, no request signing).

Integrity is checked on every download: the HTTP ``Content-Length`` must equal the listed object
size, and for single-part objects (an ``ETag`` without a ``-`` part-count suffix) the MD5 of the
downloaded bytes must equal the ``ETag``. Downloads are written to a ``.part-tmp`` sidecar and
atomically :func:`os.replace`-d into place, and destination paths are confined to the target
directory (keys that would escape via a parent reference are rejected).
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlencode


@dataclass
class S3Object:
    """One object in an S3 listing (a single ``Contents`` entry)."""

    #: The object key (its path within the bucket).
    key: str
    #: Object size in bytes.
    size: int
    #: ETag with surrounding quotes removed; a ``-`` marks a multipart upload (not a plain MD5).
    etag: str


def _local(tag: str) -> str:
    """Strip an XML namespace from a tag (``{uri}Tag`` becomes ``Tag``)."""
    return tag.rsplit("}", 1)[-1]


def parse_list_xml(xml_bytes: bytes) -> tuple[list[S3Object], str | None]:
    """Parse an S3 ``ListBucketResult`` (ListObjectsV2) response.

    The parse is namespace-tolerant — the default S3 XML namespace on every tag is stripped.

    Parameters
    ----------
    xml_bytes : bytes
        The raw XML response body.

    Returns
    -------
    tuple of (list of S3Object, str or None)
        The objects on this page and the ``NextContinuationToken`` for the following page, or
        ``None`` when the listing is not truncated.
    """
    root = ET.fromstring(xml_bytes)
    objects: list[S3Object] = []
    next_token: str | None = None
    is_truncated = False
    for child in root:
        tag = _local(child.tag)
        if tag == "Contents":
            key = etag = ""
            size = 0
            for sub in child:
                sub_tag = _local(sub.tag)
                if sub_tag == "Key":
                    key = sub.text or ""
                elif sub_tag == "Size":
                    size = int((sub.text or "0").strip())
                elif sub_tag == "ETag":
                    etag = (sub.text or "").strip().strip('"')
            objects.append(S3Object(key=key, size=size, etag=etag))
        elif tag == "IsTruncated":
            is_truncated = (child.text or "").strip().lower() == "true"
        elif tag == "NextContinuationToken":
            next_token = (child.text or "").strip() or None
    return objects, (next_token if is_truncated else None)


def _read(url: str, *, timeout: float) -> tuple[bytes, int | None]:
    """Anonymous ``GET`` of ``url``; return ``(body, content_length_header_or_None)``."""
    resp = urllib.request.urlopen(url, timeout=timeout)
    try:
        data = resp.read()
        header = resp.headers.get("Content-Length") if getattr(resp, "headers", None) else None
    finally:
        closer = getattr(resp, "close", None)
        if callable(closer):
            closer()
    return data, (int(header) if header is not None else None)


def list_prefix(endpoint: str, prefix: str, *, timeout: float = 60.0) -> list[S3Object]:
    """List every object under ``prefix`` at an S3-compatible ``endpoint`` (ListObjectsV2).

    Follows ``NextContinuationToken`` pagination until the listing is exhausted.

    Parameters
    ----------
    endpoint : str
        Bucket endpoint URL, e.g. ``"https://host/bucket"``.
    prefix : str
        Key prefix to list.
    timeout : float, optional
        Per-request timeout in seconds. Default 60.

    Returns
    -------
    list of S3Object
        Every listed object under ``prefix``.
    """
    base = endpoint.rstrip("/")
    objects: list[S3Object] = []
    token: str | None = None
    while True:
        params = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
        if token:
            params["continuation-token"] = token
        data, _ = _read(f"{base}/?{urlencode(params)}", timeout=timeout)
        page, token = parse_list_xml(data)
        objects.extend(page)
        if not token:
            return objects


def _within(base: Path, target: Path) -> bool:
    """True when ``target`` resolves inside (or equal to) ``base``."""
    return target == base or target.is_relative_to(base)


def _md5_bytes(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _md5_file(path: Path, *, chunk: int = 1 << 20) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _relative_key(key: str, strip: str) -> str:
    """The object key with ``strip`` removed from its front, as a relative path."""
    rel = key[len(strip):] if strip and key.startswith(strip) else key
    return rel.lstrip("/")


def fetch_prefix(
    endpoint: str,
    prefix: str,
    dest_dir: str | Path,
    *,
    strip_prefix: str | None = None,
    jobs: int = 4,
    resume: bool = True,
    timeout: float = 120.0,
) -> dict:
    """Download every object under ``prefix`` into ``dest_dir`` with integrity verification.

    Each object is written to ``dest_dir / <key with strip_prefix removed>``. Downloads go to a
    ``.part-tmp`` sidecar first and are atomically :func:`os.replace`-d into place. The HTTP
    ``Content-Length`` is checked against the listed size for every object, and single-part ETags
    are verified as MD5. With ``resume`` set, an existing file whose size (and, when checkable, MD5)
    already matches is left untouched.

    Parameters
    ----------
    endpoint : str
        Bucket endpoint URL.
    prefix : str
        Key prefix to fetch.
    dest_dir : str or pathlib.Path
        Local destination directory (created as needed). Keys that would resolve outside it are
        rejected.
    strip_prefix : str or None, optional
        The portion removed from the front of each key to form its local path. Defaults to
        ``prefix``.
    jobs : int, optional
        Number of concurrent download threads. Default 4.
    resume : bool, optional
        Skip files that are already complete. Default ``True``.
    timeout : float, optional
        Per-request timeout in seconds. Default 120.

    Returns
    -------
    dict
        A manifest with keys ``endpoint``, ``prefix``, ``n_objects``, ``total_bytes``, ``files``
        and ``errors``. Each ``files`` entry is ``{"key", "size", "etag", "verify"}`` where
        ``verify`` is one of ``"md5"``, ``"size"`` or ``"skip"``.

    Raises
    ------
    RuntimeError
        If any object failed to download or verify (or was rejected as an unsafe path). Every other
        object is processed first; the manifest is attached to the exception as ``exc.manifest``.
    """
    dest = Path(dest_dir)
    base_resolved = dest.resolve()
    strip = prefix if strip_prefix is None else strip_prefix
    endpoint_base = endpoint.rstrip("/")
    objects = list_prefix(endpoint, prefix, timeout=timeout)

    def _one(obj: S3Object) -> tuple[bool, dict]:
        try:
            rel = _relative_key(obj.key, strip)
            if not rel:
                return True, {"key": obj.key, "error": "empty destination path"}
            final = dest / rel
            if not _within(base_resolved, final.resolve()):
                return True, {"key": obj.key, "error": "unsafe path (escapes destination)"}

            can_md5 = bool(obj.etag) and "-" not in obj.etag
            if resume and final.exists() and final.stat().st_size == obj.size:
                if not can_md5 or _md5_file(final) == obj.etag:
                    return False, {"key": obj.key, "size": obj.size, "etag": obj.etag,
                                   "verify": "skip"}

            data, content_length = _read(
                f"{endpoint_base}/{quote(obj.key, safe='/')}", timeout=timeout)
            if content_length is None or content_length != obj.size:
                return True, {"key": obj.key,
                              "error": f"Content-Length {content_length} != size {obj.size}"}
            if len(data) != obj.size:
                return True, {"key": obj.key,
                              "error": f"received {len(data)} bytes, expected {obj.size}"}
            verify = "size"
            if can_md5:
                digest = _md5_bytes(data)
                if digest != obj.etag:
                    return True, {"key": obj.key, "error": f"MD5 {digest} != ETag {obj.etag}"}
                verify = "md5"

            final.parent.mkdir(parents=True, exist_ok=True)
            tmp = final.with_name(final.name + ".part-tmp")
            tmp.write_bytes(data)
            os.replace(tmp, final)
            return False, {"key": obj.key, "size": obj.size, "etag": obj.etag, "verify": verify}
        except Exception as exc:  # recorded per object; re-raised in aggregate below
            return True, {"key": obj.key, "error": f"{type(exc).__name__}: {exc}"}

    results: list[tuple[bool, dict]] = [(False, {})] * len(objects)
    with ThreadPoolExecutor(max_workers=max(jobs, 1)) as pool:
        futures = {pool.submit(_one, obj): i for i, obj in enumerate(objects)}
        for fut, idx in futures.items():
            results[idx] = fut.result()

    files = [rec for is_err, rec in results if not is_err]
    errors = [rec for is_err, rec in results if is_err]
    manifest = {
        "endpoint": endpoint,
        "prefix": prefix,
        "n_objects": len(objects),
        "total_bytes": sum(o.size for o in objects),
        "files": files,
        "errors": errors,
    }
    if errors:
        summary = "; ".join(f"{e['key']}: {e['error']}" for e in errors)
        exc = RuntimeError(f"{len(errors)} object(s) failed: {summary}")
        exc.manifest = manifest  # type: ignore[attr-defined]
        raise exc
    return manifest


def save_manifest(manifest: dict, path: str | Path) -> None:
    """Write a fetch ``manifest`` to ``path`` as indented JSON."""
    with Path(path).open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
