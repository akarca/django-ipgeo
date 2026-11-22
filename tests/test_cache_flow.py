"""Unit tests for the GeoIP cache-first download flow."""
import os
import sys
from unittest.mock import patch, MagicMock

import django
from django.conf import settings


def _setup_django():
    if not settings.configured:
        settings.configure(
            DEBUG=False,
            INSTALLED_APPS=["ipgeo"],
            IPGEO={
                "LOCAL_DB_PATH": "/tmp/test-geoip.mmdb",
                "LOCAL_DB_LICENSE_KEY": "fake-key",
                "LOCAL_DB_EDITION": "GeoLite2-City",
                "LOCAL_DB_UPDATE_DAYS": 60,
                "CACHE_URL": "https://cache.example.com/{edition}/",
                "CACHE_UPLOAD_TOKEN": "test-token",
            },
        )
        django.setup()


_setup_django()

sys.path.insert(0, "/Users/serdar/workspace/django-ipgeo")
from ipgeo.engine import (
    MMDB_METADATA_MARKER, _claim_download_slot, _download_db, _fetch_from_cache, is_mmdb,
)


def _mmdb_bytes():
    # Real MaxMind DBs start with the search tree (no fixed bytes) and end
    # with a metadata section introduced by this marker.
    return b"\x00\x00\x01\x00" + b"\x00" * 100 + MMDB_METADATA_MARKER + b"meta"


def test_cache_hit_returns_true(tmp_path):
    """When the cache returns a valid mmdb, we use it and never hit MaxMind."""
    dest = str(tmp_path / "city.mmdb")

    with patch("ipgeo.engine._http_download") as mock_download, \
         patch("ipgeo.engine.urlopen") as mock_maxmind:
        # Cache returns a real-looking mmdb file
        def fake_download(url, dest_path, *args, **kwargs):
            with open(dest_path, "wb") as fh:
                fh.write(_mmdb_bytes())
            return True
        mock_download.side_effect = fake_download

        result = _fetch_from_cache(
            "https://cache.example.com/{edition}/", "GeoLite2-City", dest
        )

    assert result is True
    assert os.path.exists(dest)
    with open(dest, "rb") as fh:
        assert fh.read() == _mmdb_bytes()
    mock_maxmind.assert_not_called()


def test_cache_misses_when_url_returns_html(tmp_path):
    """If the cache returns an HTML error page, we reject it and fall through."""
    dest = str(tmp_path / "city.mmdb")

    with patch("ipgeo.engine._http_download") as mock_download:
        def fake_download(url, dest_path, *args, **kwargs):
            with open(dest_path, "wb") as fh:
                fh.write(b"<html>error</html>")
            return True
        mock_download.side_effect = fake_download

        result = _fetch_from_cache(
            "https://cache.example.com/{edition}/", "GeoLite2-City", dest
        )

    assert result is False
    assert not os.path.exists(dest)


def test_cache_misses_when_url_404s(tmp_path):
    """404 from the cache URL must not crash, just fall through."""
    dest = str(tmp_path / "city.mmdb")
    from urllib.error import HTTPError

    with patch("ipgeo.engine._http_download", side_effect=HTTPError(None, 404, "Not Found", {}, None)):
        result = _fetch_from_cache(
            "https://cache.example.com/{edition}/", "GeoLite2-City", dest
        )

    assert result is False


def test_download_db_prefers_cache_over_maxmind(tmp_path):
    """End-to-end: cache hit must short-circuit MaxMind entirely."""
    db_path = str(tmp_path / "city.mmdb")
    tmp_mmdb = db_path + ".download.mmdb"

    def fake_fetch_from_cache(*args, **kwargs):
        # Simulate the real cache fetch: write the tmp file, then return True.
        with open(tmp_mmdb, "wb") as fh:
            fh.write(_mmdb_bytes())
        return True

    with patch("ipgeo.engine._fetch_from_cache", side_effect=fake_fetch_from_cache), \
         patch("ipgeo.engine._http_download") as mock_http, \
         patch("ipgeo.engine._upload_to_cache") as mock_upload:
        _download_db(db_path, "key", "GeoLite2-City")

    mock_http.assert_not_called()  # MaxMind never touched
    mock_upload.assert_not_called()  # nothing to upload, got it from cache
    assert os.path.exists(db_path)
    with open(db_path, "rb") as fh:
        assert fh.read() == _mmdb_bytes()


def test_download_db_uploads_to_cache_on_maxmind_success(tmp_path):
    """Cache miss -> MaxMind -> re-upload so next consumer benefits."""
    db_path = str(tmp_path / "city.mmdb")
    tar_bytes = b"fake-tar-bytes"  # we'll mock tarfile, not actually parse

    with patch("ipgeo.engine._fetch_from_cache", return_value=False), \
         patch("ipgeo.engine._http_download") as mock_http, \
         patch("ipgeo.engine._upload_to_cache") as mock_upload, \
         patch("ipgeo.engine.tarfile") as mock_tar:
        mock_http.return_value = True
        mock_member = MagicMock()
        mock_member.name = "GeoLite2-City.mmdb"
        mock_tf = MagicMock()
        mock_tf.__enter__.return_value.getmembers.return_value = [mock_member]
        mock_tf.__enter__.return_value.extractfile.return_value.__enter__.return_value.read.return_value = _mmdb_bytes()
        mock_tar.open.return_value = mock_tf

        _download_db(db_path, "key", "GeoLite2-City")

    assert mock_http.call_count == 1  # only the MaxMind download
    mock_upload.assert_called_once()
    assert os.path.exists(db_path)


def test_is_mmdb_rejects_old_header_only_check(tmp_path):
    """The old 0x00010203 header check rejected every real DB; a file with
    that header but no metadata marker is not a DB."""
    fake = tmp_path / "fake.mmdb"
    fake.write_bytes(b"\x00\x01\x02\x03" + b"\x00" * 100)
    real = tmp_path / "real.mmdb"
    real.write_bytes(_mmdb_bytes())
    assert not is_mmdb(str(fake))
    assert is_mmdb(str(real))
    assert not is_mmdb(str(tmp_path / "missing.mmdb"))


def test_claim_slot_backs_off_after_attempt(tmp_path):
    """After one attempt, no process tries again within the retry window."""
    db_path = str(tmp_path / "city.mmdb")
    first = _claim_download_slot(db_path, 6)
    assert first not in (False, None)
    first.close()
    assert _claim_download_slot(db_path, 6) is False
    # Retry window over -> allowed again
    old = os.path.getmtime(db_path + ".attempt") - 7 * 3600
    os.utime(db_path + ".attempt", (old, old))
    again = _claim_download_slot(db_path, 6)
    assert again not in (False, None)
    again.close()


def test_claim_slot_refuses_while_other_process_holds_lock(tmp_path):
    db_path = str(tmp_path / "city.mmdb")
    holder = _claim_download_slot(db_path, 0)
    assert holder not in (False, None)
    try:
        assert _claim_download_slot(db_path, 0) is False
    finally:
        holder.close()


if __name__ == "__main__":
    import tempfile
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))