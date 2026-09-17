"""Upload/filename/path safety helpers shared by every route.

Nothing here duplicates compliance logic - this is purely "is this upload
safe to write to disk and read as text", independent of what the text means.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

# Max size for one uploaded device-config file. Real Cisco running-configs
# are a few KB to a few hundred KB; this is generous headroom, not a
# realistic-size assumption.
MAX_UPLOAD_BYTES = 2 * 1024 * 1024  # 2 MiB

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class UploadRejected(Exception):
    """A file failed validation before being written to disk. `reason` is
    shown to the user as-is - keep it free of paths/tracebacks."""

    def __init__(self, filename: str, reason: str):
        self.filename = filename
        self.reason = reason
        super().__init__(f"{filename}: {reason}")


def sanitize_filename(raw_name: str) -> str:
    """Collapse a possibly-hostile filename (path separators, unicode
    tricks, leading dots) down to a flat, safe basename. Never trust the
    client-supplied filename as a real path component until it's passed
    through this."""
    # Take only the final path segment - strips any directory traversal
    # attempt (../../etc/passwd, C:\..\..) regardless of separator style.
    name = raw_name.replace("\\", "/").split("/")[-1]
    name = unicodedata.normalize("NFKC", name).strip()
    name = _SAFE_NAME_RE.sub("_", name)
    name = name.lstrip(".")  # no hidden files, no bare ".."  after the strip above
    if not name:
        name = "unnamed.txt"
    if not name.lower().endswith(".txt"):
        name += ".txt"
    return name


def resolve_within(root: Path, *parts: str) -> Path:
    """Join `parts` onto `root` and assert the result is still inside
    `root` once resolved. Raises ValueError instead of ever returning a
    path that escaped - use this for every disk write/read whose final
    component came from user input (a filename, a profile name)."""
    root = root.resolve()
    candidate = root.joinpath(*parts).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"Path escapes the allowed root: {parts!r}")
    return candidate


def validate_upload_bytes(filename: str, content: bytes) -> str:
    """Validate an uploaded device-config file's content. Returns the
    decoded text on success; raises UploadRejected with a user-facing
    reason otherwise. Checked server-side regardless of what the browser's
    <input accept> or extension check already did."""
    if not filename.lower().endswith(".txt"):
        raise UploadRejected(filename, "Only .txt configuration files are accepted.")
    if len(content) == 0:
        raise UploadRejected(filename, "File is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise UploadRejected(
            filename, f"File exceeds the {MAX_UPLOAD_BYTES // 1024} KB upload limit."
        )
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise UploadRejected(filename, "File is not valid UTF-8 text (looks like a binary file).") from None
    if not text.strip():
        raise UploadRejected(filename, "File contains no content.")
    return text


def sanitize_profile_name(raw_name: str) -> str:
    """Like sanitize_filename, but for a Golden Config profile name (no
    forced .txt suffix, used as a directory name)."""
    name = unicodedata.normalize("NFKC", raw_name).strip()
    name = _SAFE_NAME_RE.sub("_", name)
    name = name.strip("._") or "profile"
    return name[:80]
