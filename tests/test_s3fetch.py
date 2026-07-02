"""Tests for the anonymous S3 fetcher (s3fetch.py) — no network access.

The listing parser is exercised against embedded ``ListBucketResult`` XML, and the download /
verification logic against a fake :func:`urllib.request.urlopen` (monkeypatched) so nothing touches
the network.
"""

from __future__ import annotations

import hashlib
import json
import urllib.request
from urllib.parse import quote

import pytest

from s2_msi_raw_generator import s3fetch

_NS = "http://s3.amazonaws.com/doc/2006-03-01/"

# Two-page ListBucketResult fixture: page 1 is truncated with a NextContinuationToken; page 2 is
# final. Note the quoted ETags and the multipart marker ("bbbb-2") on the second object.
PAGE1 = (
    f'<?xml version="1.0" encoding="UTF-8"?>\n'
    f'<ListBucketResult xmlns="{_NS}">'
    f"<Name>bucket</Name><Prefix>data/</Prefix>"
    f"<IsTruncated>true</IsTruncated>"
    f"<NextContinuationToken>TOKEN2</NextContinuationToken>"
    f'<Contents><Key>data/a.bin</Key><Size>10</Size><ETag>&quot;aaaa&quot;</ETag></Contents>'
    f'<Contents><Key>data/b.bin</Key><Size>20</Size><ETag>&quot;bbbb-2&quot;</ETag></Contents>'
    f"</ListBucketResult>"
).encode("utf-8")

PAGE2 = (
    f'<?xml version="1.0" encoding="UTF-8"?>\n'
    f'<ListBucketResult xmlns="{_NS}">'
    f"<Name>bucket</Name><Prefix>data/</Prefix>"
    f"<IsTruncated>false</IsTruncated>"
    f'<Contents><Key>data/c.bin</Key><Size>30</Size><ETag>&quot;cccc&quot;</ETag></Contents>'
    f"</ListBucketResult>"
).encode("utf-8")


_AUTO = object()


class _FakeResp:
    """Minimal stand-in for a ``urlopen`` response: ``.read()`` + ``.headers.get(...)``."""

    def __init__(self, data: bytes, content_length=_AUTO):
        self.data = data
        if content_length is _AUTO:
            value: str | None = str(len(data))
        elif content_length is None:
            value = None
        else:
            value = str(content_length)
        self.headers = {"Content-Length": value}

    def read(self) -> bytes:
        return self.data

    def close(self) -> None:
        pass


def _make_transport(objects, *, calls=None):
    """Build a fake ``urlopen`` serving one ListBucketResult page plus each object's bytes.

    ``objects`` is a list of dicts ``{key, data, etag, size?, content_length?}``. Object fetches
    (not the listing request) are appended to ``calls`` when given.
    """
    rows = []
    responses = {}
    for obj in objects:
        size = obj.get("size", len(obj["data"]))
        rows.append(
            f"<Contents><Key>{obj['key']}</Key><Size>{size}</Size>"
            f"<ETag>&quot;{obj['etag']}&quot;</ETag></Contents>")
        responses[obj["key"]] = _FakeResp(obj["data"], obj.get("content_length", _AUTO))
    list_xml = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<ListBucketResult xmlns="{_NS}"><IsTruncated>false</IsTruncated>'
        + "".join(rows) + "</ListBucketResult>"
    ).encode("utf-8")

    def fake_urlopen(url, timeout=None):
        if "list-type=2" in url:
            return _FakeResp(list_xml)
        for key, resp in responses.items():
            if url.endswith(quote(key, safe="/")):
                if calls is not None:
                    calls.append(key)
                return resp
        raise AssertionError(f"unexpected URL requested: {url}")

    return fake_urlopen


def test_parse_list_xml_page1_truncated_with_token():
    objs, token = s3fetch.parse_list_xml(PAGE1)
    assert token == "TOKEN2"
    assert [o.key for o in objs] == ["data/a.bin", "data/b.bin"]
    assert objs[0].size == 10 and objs[0].etag == "aaaa"   # surrounding quotes stripped
    assert objs[1].etag == "bbbb-2"                        # multipart marker retained


def test_parse_list_xml_page2_final_has_no_token():
    objs, token = s3fetch.parse_list_xml(PAGE2)
    assert token is None
    assert len(objs) == 1 and objs[0].key == "data/c.bin" and objs[0].size == 30


def test_list_prefix_follows_continuation_token(monkeypatch):
    def fake_urlopen(url, timeout=None):
        return _FakeResp(PAGE2) if "continuation-token=TOKEN2" in url else _FakeResp(PAGE1)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    objs = s3fetch.list_prefix("https://host/bucket", "data/")
    assert [o.key for o in objs] == ["data/a.bin", "data/b.bin", "data/c.bin"]


def test_fetch_single_part_md5_verified(tmp_path, monkeypatch):
    data = b"0123456789"
    etag = hashlib.md5(data).hexdigest()
    monkeypatch.setattr(urllib.request, "urlopen",
                        _make_transport([{"key": "data/a.bin", "data": data, "etag": etag}]))
    manifest = s3fetch.fetch_prefix("https://host/bucket", "data/", tmp_path)
    assert manifest["errors"] == []
    assert manifest["n_objects"] == 1 and manifest["total_bytes"] == 10
    assert manifest["files"][0]["verify"] == "md5"
    assert (tmp_path / "a.bin").read_bytes() == data


def test_fetch_md5_mismatch_raises_and_attaches_manifest(tmp_path, monkeypatch):
    data = b"payload!!"  # single-part etag below is deliberately wrong
    monkeypatch.setattr(urllib.request, "urlopen",
                        _make_transport([{"key": "data/x.bin", "data": data, "etag": "deadbeef"}]))
    with pytest.raises(RuntimeError) as excinfo:
        s3fetch.fetch_prefix("https://host/bucket", "data/", tmp_path)
    assert "x.bin" in str(excinfo.value)
    assert excinfo.value.manifest["errors"][0]["key"] == "data/x.bin"
    assert not (tmp_path / "x.bin").exists()  # failed verification leaves no final file


def test_fetch_multipart_etag_is_size_only(tmp_path, monkeypatch):
    data = b"multipart-body"
    monkeypatch.setattr(urllib.request, "urlopen",
                        _make_transport([{"key": "data/m.bin", "data": data, "etag": "whatever-3"}]))
    manifest = s3fetch.fetch_prefix("https://host/bucket", "data/", tmp_path)
    assert manifest["files"][0]["verify"] == "size"
    assert (tmp_path / "m.bin").read_bytes() == data


def test_fetch_content_length_mismatch_raises(tmp_path, monkeypatch):
    data = b"1234567890"
    etag = hashlib.md5(data).hexdigest()
    # listed Size matches the data, but the HTTP Content-Length header lies.
    monkeypatch.setattr(urllib.request, "urlopen", _make_transport(
        [{"key": "data/z.bin", "data": data, "etag": etag, "content_length": 999}]))
    with pytest.raises(RuntimeError) as excinfo:
        s3fetch.fetch_prefix("https://host/bucket", "data/", tmp_path)
    assert "Content-Length" in str(excinfo.value)


def test_fetch_resume_skips_existing_verified_file(tmp_path, monkeypatch):
    data = b"already-here"
    etag = hashlib.md5(data).hexdigest()
    (tmp_path / "r.bin").write_bytes(data)  # pre-existing, correct size + md5
    calls: list[str] = []
    monkeypatch.setattr(urllib.request, "urlopen", _make_transport(
        [{"key": "data/r.bin", "data": data, "etag": etag}], calls=calls))
    manifest = s3fetch.fetch_prefix("https://host/bucket", "data/", tmp_path)
    assert manifest["files"][0]["verify"] == "skip"
    assert calls == []  # the object body was never fetched


def test_fetch_rejects_path_traversal(tmp_path, monkeypatch):
    data = b"evil"
    etag = hashlib.md5(data).hexdigest()
    # Key escapes the prefix with a parent reference; prefix "safe/" does not strip it.
    monkeypatch.setattr(urllib.request, "urlopen",
                        _make_transport([{"key": "../evil.bin", "data": data, "etag": etag}]))
    with pytest.raises(RuntimeError) as excinfo:
        s3fetch.fetch_prefix("https://host/bucket", "safe/", tmp_path)
    errors = excinfo.value.manifest["errors"]
    assert errors and errors[0]["key"] == "../evil.bin" and "unsafe" in errors[0]["error"]
    assert not (tmp_path.parent / "evil.bin").exists()  # nothing written outside the destination


def test_fetch_strip_prefix_controls_local_layout(tmp_path, monkeypatch):
    data = b"nested-file"
    etag = hashlib.md5(data).hexdigest()
    monkeypatch.setattr(urllib.request, "urlopen", _make_transport(
        [{"key": "granule/DS/sub/file.bin", "data": data, "etag": etag}]))
    manifest = s3fetch.fetch_prefix(
        "https://host/bucket", "granule/", tmp_path, strip_prefix="granule/DS/")
    assert manifest["errors"] == []
    assert (tmp_path / "sub" / "file.bin").read_bytes() == data


def test_save_manifest_writes_indented_json(tmp_path):
    manifest = {"endpoint": "e", "prefix": "p", "n_objects": 0,
                "total_bytes": 0, "files": [], "errors": []}
    out = tmp_path / "manifest.json"
    s3fetch.save_manifest(manifest, out)
    text = out.read_text(encoding="utf-8")
    assert json.loads(text) == manifest
    assert "\n  " in text  # indent=2 applied
