from __future__ import annotations

from app.ports.document_reader import DocumentReader as BinaryReader
from utils.storage import read_binary


class StorageBinaryReader(BinaryReader):
    def read(self, file_uri: str) -> bytes:
        return read_binary(file_uri)
