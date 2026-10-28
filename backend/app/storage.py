"""Safe local-volume storage for original uploaded files."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from app.contracts import ErrorCode, PipelineError


class Storage(ABC):
    @abstractmethod
    def save(self, source: BinaryIO) -> str: ...

    @abstractmethod
    def open(self, key: str) -> BinaryIO: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...


class LocalStorage(Storage):
    """Stores opaque UUID keys below one configured root directory."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if not key or Path(key).name != key:
            raise PipelineError(ErrorCode.STORAGE_ERROR, "invalid storage key")
        path = (self.root / key).resolve()
        if path.parent != self.root:
            raise PipelineError(ErrorCode.STORAGE_ERROR, "storage key escapes root")
        return path

    def save(self, source: BinaryIO) -> str:
        key = uuid4().hex
        path = self._path(key)
        try:
            with path.open("xb") as destination:
                while chunk := source.read(1024 * 1024):
                    destination.write(chunk)
        except OSError as exc:
            raise PipelineError(ErrorCode.STORAGE_ERROR, "could not save uploaded file") from exc
        return key

    def open(self, key: str) -> BinaryIO:
        try:
            return self._path(key).open("rb")
        except OSError as exc:
            raise PipelineError(ErrorCode.STORAGE_ERROR, "stored file is unavailable") from exc

    def delete(self, key: str) -> None:
        try:
            self._path(key).unlink(missing_ok=True)
        except OSError as exc:
            raise PipelineError(ErrorCode.STORAGE_ERROR, "could not delete stored file") from exc
