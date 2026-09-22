"""Tests de reanudación de descarga (comportamiento del rango HTTP)."""

from collections.abc import Iterator
from pathlib import Path

from src.downloader import TSRDownloader


class _FakeResponse:
    def __init__(self, status: int, headers: dict[str, str], chunks: list[bytes]) -> None:
        self.status_code = status
        self.headers = headers
        self._chunks = chunks

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size: int) -> Iterator[bytes]:
        yield from self._chunks


class _FakeSession:
    """Session mínima: HEAD con nombre/tamaño y GET con el status elegido."""

    def __init__(self, status: int, chunks: list[bytes]) -> None:
        self.status = status
        self.chunks = chunks
        self.sent_range: str | None = None

    def head(self, url: str, **kwargs: object) -> _FakeResponse:
        headers = {
            "Content-Disposition": 'filename="file.zip"',
            "Content-Length": str(sum(len(c) for c in self.chunks)),
        }
        return _FakeResponse(200, headers, [])

    def get(self, url: str, **kwargs: object) -> _FakeResponse:
        headers = kwargs.get("headers")
        self.sent_range = headers.get("Range") if isinstance(headers, dict) else None
        return _FakeResponse(self.status, {}, self.chunks)


def _downloader(session: _FakeSession) -> TSRDownloader:
    dl = TSRDownloader(session, item_id=1, authenticated=True)  # type: ignore[arg-type]
    dl.get_url = lambda: "http://example.invalid/file.zip"  # type: ignore[method-assign]
    return dl


def test_range_ignored_rewrites_from_scratch(tmp_path: Path) -> None:
    """Si el servidor responde 200 a un Range, el .part se reescribe (no se concatena)."""
    part = tmp_path / "file.zip.part"
    part.write_bytes(b"0123456789")
    full = b"0123456789abcdefghij"  # 20 bytes: el archivo completo
    session = _FakeSession(status=200, chunks=[full])

    _downloader(session).download(tmp_path)

    assert session.sent_range == "bytes=10-"  # sí se pidió el rango
    assert (tmp_path / "file.zip").read_bytes() == full  # 20 bytes, no 30
    assert not part.exists()


def test_range_resumed_appends(tmp_path: Path) -> None:
    """Con 206 se continúa en el archivo parcial existente."""
    part = tmp_path / "file.zip.part"
    part.write_bytes(b"0123456789")
    session = _FakeSession(status=206, chunks=[b"abcdefghij"])

    _downloader(session).download(tmp_path)

    assert (tmp_path / "file.zip").read_bytes() == b"0123456789abcdefghij"
    assert not part.exists()
