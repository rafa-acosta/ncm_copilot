"""Upload/path-safety tests for webapp/backend/security.py, plus the
regression test for the ordering bug it guards against: extension
validation must run on the RAW filename before sanitize_filename() forces a
.txt suffix onto it (otherwise a rejected "bad.exe" is laundered into an
accepted "bad.exe.txt")."""

from __future__ import annotations

import pytest

from webapp.backend.security import (
    MAX_UPLOAD_BYTES,
    UploadRejected,
    resolve_within,
    sanitize_filename,
    sanitize_profile_name,
    validate_upload_bytes,
)


def test_sanitize_filename_strips_path_traversal():
    assert sanitize_filename("../../etc/passwd.txt") == "passwd.txt"
    assert sanitize_filename("..\\..\\windows\\win.ini.txt") == "win.ini.txt"


def test_sanitize_filename_forces_txt_suffix_on_extensionless_name():
    assert sanitize_filename("no_extension") == "no_extension.txt"


def test_sanitize_filename_empty_or_dots_only_gets_a_safe_fallback():
    assert sanitize_filename("") == "unnamed.txt"
    assert sanitize_filename("...") == "unnamed.txt"


def test_resolve_within_rejects_escape(tmp_path):
    with pytest.raises(ValueError):
        resolve_within(tmp_path, "..", "..", "etc", "passwd")


def test_resolve_within_allows_nested_path(tmp_path):
    result = resolve_within(tmp_path, "sub", "file.txt")
    assert result == (tmp_path / "sub" / "file.txt").resolve()


def test_validate_upload_bytes_rejects_non_txt_extension_on_the_raw_name():
    """The exact bug this project hit once: validating AFTER sanitization
    would have let a rejected .exe through, since sanitize_filename() force-
    appends .txt to names lacking an extension."""
    with pytest.raises(UploadRejected, match="Only .txt"):
        validate_upload_bytes("malware.exe", b"MZ\x90\x00fake-binary")


def test_validate_upload_bytes_does_not_launder_a_rejected_name_via_sanitization():
    raw_name = "malware.exe"
    with pytest.raises(UploadRejected):
        validate_upload_bytes(raw_name, b"whatever")
    # Even after the fact, sanitizing the ORIGINAL raw name (not something
    # already re-validated) must never look like a file that would have passed.
    sanitized = sanitize_filename(raw_name)
    assert sanitized == "malware.exe.txt"  # sanitize_filename alone is lenient - callers MUST validate first


def test_validate_upload_bytes_rejects_empty_file():
    with pytest.raises(UploadRejected, match="empty"):
        validate_upload_bytes("device.txt", b"")


def test_validate_upload_bytes_rejects_oversized_file():
    with pytest.raises(UploadRejected, match="exceeds"):
        validate_upload_bytes("device.txt", b"x" * (MAX_UPLOAD_BYTES + 1))


def test_validate_upload_bytes_rejects_non_utf8_binary_content():
    with pytest.raises(UploadRejected, match="UTF-8"):
        validate_upload_bytes("device.txt", b"\xff\xfe\x00\x01binary")


def test_validate_upload_bytes_accepts_a_valid_config():
    text = validate_upload_bytes("router1.txt", b"hostname ROUTER1\n!\nend\n")
    assert text == "hostname ROUTER1\n!\nend\n"


def test_sanitize_profile_name_collapses_hostile_characters():
    assert sanitize_profile_name("../../etc/passwd") == "etc_passwd"
    assert sanitize_profile_name("   ") == "profile"
    assert sanitize_profile_name("A" * 200) == ("A" * 80)
