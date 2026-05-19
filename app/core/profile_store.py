import json
import re
from pathlib import Path

from app.core.config import AppConfig


_SAFE_PROFILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class ProfileStore:
    """Filesystem-backed AppConfig profile store."""

    def __init__(self, profiles_dir: Path) -> None:
        self.profiles_dir = profiles_dir
        self._active_path = self.profiles_dir / "active_profile.txt"

    def save(self, name: str, config: AppConfig) -> Path:
        path = self._profile_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = config.model_dump(mode="json")
        payload.get("api", {}).pop("api_key", None)
        temp_path = path.with_suffix(".json.tmp")
        temp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(path)
        return path

    def load(self, name: str) -> AppConfig:
        path = self._profile_path(name)
        if not path.exists():
            raise FileNotFoundError(f"profile not found: {name}")
        return AppConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def list_profiles(self) -> list[str]:
        if not self.profiles_dir.exists():
            return []
        return sorted(path.stem for path in self.profiles_dir.glob("*.json") if path.is_file())

    def delete(self, name: str) -> bool:
        path = self._profile_path(name)
        existed = path.exists()
        if existed:
            path.unlink()
        if self.active_profile() == name and self._active_path.exists():
            self._active_path.unlink()
        return existed

    def switch(self, name: str) -> None:
        self.load(name)
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        self._active_path.write_text(name + "\n", encoding="utf-8")

    def active_profile(self) -> str | None:
        if not self._active_path.exists():
            return None
        name = self._active_path.read_text(encoding="utf-8").strip()
        if not name:
            return None
        try:
            self._validate_name(name)
        except ValueError:
            return None
        if not self._profile_path(name).exists():
            return None
        return name

    def load_active(self) -> AppConfig:
        name = self.active_profile()
        if name is None:
            raise FileNotFoundError("no active profile")
        return self.load(name)

    def _profile_path(self, name: str) -> Path:
        safe_name = self._validate_name(name)
        return self.profiles_dir / f"{safe_name}.json"

    @staticmethod
    def _validate_name(name: str) -> str:
        if not _SAFE_PROFILE_NAME.fullmatch(name):
            raise ValueError("profile name must use letters, numbers, dot, underscore, or hyphen")
        if name.endswith(".") or name.endswith(" "):
            raise ValueError("profile name must be safe as a filename")
        if name.upper() in _WINDOWS_RESERVED_NAMES:
            raise ValueError("profile name must not be a Windows reserved filename")
        return name


__all__ = ["ProfileStore"]
