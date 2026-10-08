from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct


@dataclass(frozen=True, slots=True)
class MetadataField:
    index: int
    name_index: int
    name: str
    type_index: int
    token: int


@dataclass(frozen=True, slots=True)
class MetadataType:
    index: int
    name_index: int
    namespace_index: int
    name: str
    namespace: str
    type_index: int
    field_start: int
    field_count: int
    flags: int
    bitfield: int

    @property
    def full_name(self) -> str:
        return f"{self.namespace}.{self.name}" if self.namespace else self.name


class Metadata:
    """Parse ordinary IL2CPP metadata v29/v31 without loading the game code."""

    TYPE_SIZE = 88
    FIELD_SIZE = 12

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        if len(self.data) < 256:
            raise ValueError("Truncated IL2CPP metadata")
        header = struct.unpack_from("<64I", self.data)
        if header[0] != 0xFAB11BAF or header[1] not in (29, 31):
            raise ValueError("Expected unmodified IL2CPP metadata version 29 or 31")
        self.version = header[1]
        self.string_offset, self.string_size = header[6:8]
        self.fields_offset, self.fields_size = header[24:26]
        self.types_offset, self.types_size = header[40:42]
        for offset, size in ((self.string_offset, self.string_size),
                             (self.fields_offset, self.fields_size),
                             (self.types_offset, self.types_size),
                             (header[16], header[17]), (header[18], header[19])):
            if offset + size > len(self.data):
                raise ValueError("Metadata section extends beyond file")
        if self.types_size % self.TYPE_SIZE or self.fields_size % self.FIELD_SIZE or header[17] % 12:
            raise ValueError("Unsupported metadata record layout")
        self.types = tuple(self._type(index) for index in range(self.types_size // self.TYPE_SIZE))
        self.default_data_offset = header[18]
        self.field_defaults = {}
        for offset in range(header[16], header[16] + header[17], 12):
            index, type_index, data_index = struct.unpack_from("<iii", self.data, offset)
            self.field_defaults[index] = (type_index, data_index)

    def string(self, index: int) -> str:
        if not 0 <= index < self.string_size:
            raise ValueError("Metadata string index is out of range")
        offset = self.string_offset + index
        end = self.data.find(b"\0", offset, self.string_offset + self.string_size)
        if end < 0:
            raise ValueError("Unterminated metadata string")
        return self.data[offset:end].decode("utf-8", errors="replace")

    def _type(self, index: int) -> MetadataType:
        values = struct.unpack_from("<16i8H2I", self.data, self.types_offset + index * self.TYPE_SIZE)
        return MetadataType(
            index, values[0], values[1], self.string(values[0]), self.string(values[1]),
            values[2], values[8], values[18], values[7], values[24],
        )

    def fields(self, item: MetadataType) -> tuple[MetadataField, ...]:
        result = []
        for index in range(item.field_start, item.field_start + item.field_count):
            if not 0 <= index < self.fields_size // self.FIELD_SIZE:
                raise ValueError("Metadata field index is out of range")
            name, type_index, token = struct.unpack_from("<IiI", self.data, self.fields_offset + index * self.FIELD_SIZE)
            result.append(MetadataField(index, name, self.string(name), type_index, token))
        return tuple(result)

    def matching_types(self, pattern: str) -> tuple[MetadataType, ...]:
        import re
        expression = re.compile(pattern, re.IGNORECASE)
        return tuple(item for item in self.types if expression.search(item.full_name))

    @staticmethod
    def compressed_integer(data: bytes, offset: int) -> int:
        """Decode the signed integer format used in modern metadata defaults."""
        if not 0 <= offset < len(data):
            raise ValueError("Compressed metadata integer is out of range")
        first = data[offset]
        length = 1 if first < 0x80 or first in (0xFE, 0xFF) else 2 if first < 0xC0 else 4 if first < 0xE0 else 5
        if offset + length > len(data):
            raise ValueError("Truncated compressed metadata integer")
        if first < 0x80:
            value = first
        elif first < 0xC0:
            value = ((first & 0x7F) << 8) | data[offset + 1]
        elif first < 0xE0:
            value = ((first & 0x3F) << 24) | int.from_bytes(data[offset + 1:offset + 4], "big")
        elif first == 0xF0:
            value = struct.unpack_from("<I", data, offset + 1)[0]
        elif first == 0xFE:
            value = 0xFFFFFFFE
        elif first == 0xFF:
            value = 0xFFFFFFFF
        else:
            raise ValueError("Invalid compressed metadata integer")
        if value == 0xFFFFFFFF:
            return -(2 ** 31)
        return -(value >> 1) - 1 if value & 1 else value >> 1

    def enum_values(self, name: str | MetadataType) -> dict[int, str]:
        matches = [name] if isinstance(name, MetadataType) else [item for item in self.types if item.full_name == name]
        if len(matches) != 1 or not matches[0].bitfield & 2:
            raise ValueError(f"Cannot uniquely identify enum {name}")
        result = {}
        for field in self.fields(matches[0]):
            default = self.field_defaults.get(field.index)
            if default is not None and default[1] >= 0:
                result[self.compressed_integer(self.data, self.default_data_offset + default[1])] = field.name
        return result
