from __future__ import annotations

from .memory import MemoryReader


def array_pointers(reader: MemoryReader, address: int, *, maximum: int = 10) -> tuple[int, ...]:
    if not address:
        return ()
    length = reader.unpack("<Q", address + 24)[0]
    if length > maximum:
        raise ValueError("Unexpected IL2CPP array length")
    if not length:
        return ()
    return reader.unpack("<" + "Q" * length, address + 32)


def array_integers(reader: MemoryReader, address: int, *, maximum: int = 10) -> tuple[int, ...]:
    if not address:
        return ()
    length = reader.unpack("<Q", address + 24)[0]
    if length > maximum:
        raise ValueError("Unexpected IL2CPP array length")
    return reader.unpack("<" + "i" * length, address + 32) if length else ()


def list_pointers(reader: MemoryReader, address: int, *, maximum: int = 10) -> tuple[int, ...]:
    if not address:
        return ()
    size, version = reader.unpack("<ii", address + 24)
    if not 0 <= size <= maximum:
        raise ValueError("Unexpected IL2CPP list size")
    items = reader.pointer(address + 16)
    if not items:
        if size:
            raise ValueError("Nonempty IL2CPP list has no item array")
        return ()
    capacity = reader.unpack("<Q", items + 24)[0]
    if not size <= capacity <= 4096:
        raise ValueError("Invalid IL2CPP list capacity")
    result = reader.unpack("<" + "Q" * size, items + 32) if size else ()
    if (size, version) != reader.unpack("<ii", address + 24) or items != reader.pointer(address + 16):
        raise ValueError("List changed while it was read")
    return result
