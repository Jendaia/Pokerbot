from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import struct
from typing import Iterator


@dataclass(frozen=True, slots=True)
class MemoryRegion:
    start: int
    end: int
    permissions: str
    file_offset: int
    path: str

    @property
    def size(self) -> int:
        return self.end - self.start


class MemoryReader:
    """Linux /proc reader. Opens memory O_RDONLY and never attaches or writes."""

    def __init__(self, pid: int):
        if type(pid) is not int or pid < 1:
            raise ValueError("pid must be a positive integer")
        self.pid = pid
        self.refresh_maps()
        self.fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY)

    def refresh_maps(self) -> None:
        regions = []
        for line in Path(f"/proc/{self.pid}/maps").read_text().splitlines():
            parts = line.split(maxsplit=5)
            start, end = (int(value, 16) for value in parts[0].split("-"))
            regions.append(MemoryRegion(start, end, parts[1], int(parts[2], 16), parts[5] if len(parts) == 6 else ""))
        self.regions = tuple(regions)

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def read(self, address: int, size: int) -> bytes:
        if not 0 <= address < 2 ** 63 or not 0 <= size <= 64 * 1024 * 1024 or address + size >= 2 ** 63:
            raise ValueError("Invalid memory read extent")
        data = os.pread(self.fd, size, address)
        if len(data) != size:
            raise OSError("Short process memory read")
        return data

    def unpack(self, fmt: str, address: int):
        return struct.unpack(fmt, self.read(address, struct.calcsize(fmt)))

    def pointer(self, address: int) -> int:
        return self.unpack("<Q", address)[0]

    def cstring(self, address: int, limit: int = 256) -> str:
        if not address:
            return ""
        return self.read(address, limit).split(b"\0", 1)[0].decode("utf-8", errors="replace")

    def managed_string(self, address: int, limit: int = 1024) -> str | None:
        if not address:
            return None
        length = self.unpack("<i", address + 16)[0]
        if not 0 <= length <= limit:
            raise ValueError("Invalid IL2CPP string length")
        return self.read(address + 20, length * 2).decode("utf-16-le", errors="replace")

    def mapped(self, address: int, size: int = 1) -> bool:
        return any(region.start <= address and address + size <= region.end and "r" in region.permissions
                   for region in self.regions)

    def chunks(self, *, writable: bool = True, max_region_size: int = 512 * 1024 * 1024,
               chunk_size: int = 4 * 1024 * 1024) -> Iterator[tuple[int, bytes]]:
        for region in self.regions:
            if "r" not in region.permissions or (writable and "w" not in region.permissions):
                continue
            if region.size > max_region_size or region.path.startswith(("/dev/", "/memfd:")):
                continue
            for start in range(region.start, region.end, chunk_size):
                try:
                    yield start, self.read(start, min(chunk_size, region.end - start))
                except OSError:
                    continue

    def find_pointers(self, values: set[int]) -> dict[int, list[int]]:
        """Find aligned pointer values, returning only matches rather than raw memory."""
        import numpy as np
        result = {value: [] for value in values}
        if not values:
            return result
        low, high = min(values), max(values)
        for base, data in self.chunks():
            words = np.frombuffer(data, dtype="<u8", count=len(data) // 8)
            indices = np.flatnonzero((words >= low) & (words <= high))
            for index in indices:
                value = int(words[index])
                if value in result:
                    result[value].append(base + int(index) * 8)
        return result
