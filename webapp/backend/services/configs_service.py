"""Configuration Files screen - upload/list/delete device configs.

Pure file management plus one bit of reuse: hostname detection uses the
project's own config_parser.ConfigTree (the same parser compliance_engine.py
runs on) rather than a hand-rolled regex, so "detected device name" reflects
exactly what the real analysis engine would see.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

# The existing top-level modules (config_parser.py, etc.) live at the repo
# root, one level above webapp/ - add it to sys.path once so every service
# can `import config_parser` etc. exactly like the CLI tools do.
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config_parser import ConfigTree  # noqa: E402  (see sys.path setup above)

from webapp.backend.security import UploadRejected, resolve_within, sanitize_filename, validate_upload_bytes

DATA_ROOT = Path(__file__).resolve().parents[2] / "data"
DEVICE_CONFIGS_DIR = DATA_ROOT / "device_configs"


@dataclass
class ConfigFileInfo:
    filename: str
    device_name: str | None
    size_bytes: int
    modified_at: float  # unix timestamp; the frontend formats it


@dataclass
class UploadOutcome:
    filename: str
    status: str  # "added" | "replaced" | "rejected"
    reason: str | None = None


@dataclass
class UploadResult:
    outcomes: list[UploadOutcome] = field(default_factory=list)

    @property
    def accepted_count(self) -> int:
        return sum(1 for o in self.outcomes if o.status in ("added", "replaced"))

    @property
    def rejected_count(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "rejected")


def _detect_hostname(text: str) -> str | None:
    try:
        line = ConfigTree(text).first_text(r"^hostname\s")
    except Exception:  # noqa: BLE001 - detection is best-effort, never fatal to an upload
        return None
    if not line:
        return None
    parts = line.split(None, 1)
    return parts[1].strip() if len(parts) > 1 else None


def ensure_dirs() -> None:
    DEVICE_CONFIGS_DIR.mkdir(parents=True, exist_ok=True)


def list_configs() -> list[ConfigFileInfo]:
    ensure_dirs()
    results = []
    for path in sorted(DEVICE_CONFIGS_DIR.glob("*.txt")):
        stat = path.stat()
        text = path.read_text(encoding="utf-8", errors="replace")
        results.append(
            ConfigFileInfo(
                filename=path.name,
                device_name=_detect_hostname(text),
                size_bytes=stat.st_size,
                modified_at=stat.st_mtime,
            )
        )
    return results


def save_uploads(files: list[tuple[str, bytes]]) -> UploadResult:
    """Validate and write every uploaded file. One bad file never blocks the
    others - each gets its own outcome."""
    ensure_dirs()
    result = UploadResult()
    for raw_filename, content in files:
        # Extension is checked on the RAW name first - sanitize_filename()
        # force-appends .txt to anything that lacks it (so a stray empty
        # name still lands somewhere safe), which would otherwise silently
        # launder a rejected "bad.exe" into an accepted "bad.exe.txt" if
        # sanitization ran before this check.
        try:
            text = validate_upload_bytes(raw_filename, content)
        except UploadRejected as exc:
            result.outcomes.append(UploadOutcome(filename=raw_filename, status="rejected", reason=exc.reason))
            continue

        safe_name = sanitize_filename(raw_filename)
        try:
            dest = resolve_within(DEVICE_CONFIGS_DIR, safe_name)
        except ValueError:
            result.outcomes.append(
                UploadOutcome(filename=raw_filename, status="rejected", reason="Invalid filename.")
            )
            continue

        already_existed = dest.exists()
        dest.write_text(text, encoding="utf-8")
        result.outcomes.append(
            UploadOutcome(filename=safe_name, status="replaced" if already_existed else "added")
        )
    return result


def delete_configs(filenames: list[str]) -> int:
    ensure_dirs()
    deleted = 0
    for raw_name in filenames:
        safe_name = sanitize_filename(raw_name)
        try:
            path = resolve_within(DEVICE_CONFIGS_DIR, safe_name)
        except ValueError:
            continue
        if path.exists() and path.is_file():
            path.unlink()
            deleted += 1
    return deleted


def delete_all_configs() -> int:
    ensure_dirs()
    deleted = 0
    for path in DEVICE_CONFIGS_DIR.glob("*.txt"):
        path.unlink()
        deleted += 1
    return deleted


def read_config_text(filename: str) -> str:
    path = resolve_within(DEVICE_CONFIGS_DIR, Path(filename).name)
    if not path.exists():
        raise FileNotFoundError(filename)
    return path.read_text(encoding="utf-8")
