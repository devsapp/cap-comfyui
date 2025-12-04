from abc import ABC
from .filesystem import FileSystem
from .oss import OSS
from .file_lock import FileLock


class Store(ABC):
    def get(key: str) -> str:
        pass

    def put(key: str, value: str) -> str:
        pass


__all__ = [
    FileSystem,
    Store,
    OSS,
    FileLock,
]
