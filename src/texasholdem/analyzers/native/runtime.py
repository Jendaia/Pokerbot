from __future__ import annotations

from dataclasses import dataclass
import struct

from .memory import MemoryReader
from .metadata import Metadata, MetadataType


@dataclass(frozen=True, slots=True)
class RuntimeField:
    name: str
    offset: int
    type_pointer: int
    attributes: int
    type_code: int

    @property
    def is_static(self) -> bool:
        return bool(self.attributes & 0x10)


@dataclass(frozen=True, slots=True)
class RuntimeClass:
    address: int
    metadata_type: MetadataType
    fields: tuple[RuntimeField, ...]
    parent: int
    static_fields: int


class Runtime:
    """Resolve IL2CPP classes using metadata name pointers, not fixed addresses."""

    def __init__(self, reader: MemoryReader, metadata: Metadata):
        self.reader = reader
        self.metadata = metadata
        mappings = [region for region in reader.regions
                    if region.path.endswith("/global-metadata.dat") and region.file_offset == 0]
        if len(mappings) != 1:
            raise ValueError("Cannot uniquely locate the IL2CPP metadata mapping")
        self.metadata_base = mappings[0].start

    def find_classes(self, types: tuple[MetadataType, ...]) -> dict[str, RuntimeClass]:
        addresses: dict[int, list[MetadataType]] = {}
        for item in types:
            addresses.setdefault(self.metadata_base + self.metadata.string_offset + item.name_index, []).append(item)
        references = self.reader.find_pointers(set(addresses))
        result = {}
        for name_pointer, hits in references.items():
            for item in addresses[name_pointer]:
                namespace_pointer = self.metadata_base + self.metadata.string_offset + item.namespace_index
                for hit in hits:
                    try:
                        if self.reader.pointer(hit + 8) != namespace_pointer:
                            continue
                        address = hit - 16
                        if not self.reader.mapped(address, 320):
                            continue
                        fields = self._fields(address, item)
                        result[item.full_name] = RuntimeClass(
                            address, item, fields, self.reader.pointer(address + 0x58),
                            self.reader.pointer(address + 0xB8),
                        )
                        break
                    except (OSError, ValueError):
                        continue
        return result

    def _fields(self, address: int, item: MetadataType) -> tuple[RuntimeField, ...]:
        expected = self.metadata.fields(item)
        if not expected:
            return ()
        field_array = self.reader.pointer(address + 0x80)
        if not field_array:
            return ()  # IL2CPP may not have materialized reflection metadata yet.
        result = []
        for index, field in enumerate(expected):
            name, type_pointer, parent, offset, token = self.reader.unpack("<QQQiI", field_array + index * 32)
            if parent != address or self.reader.cstring(name) != field.name or token != field.token:
                raise ValueError("Runtime field layout does not match metadata")
            bits = self.reader.unpack("<I", type_pointer + 8)[0]
            result.append(RuntimeField(field.name, offset, type_pointer, bits & 0xFFFF, (bits >> 16) & 0xFF))
        return tuple(result)

    def class_name(self, address: int) -> str:
        if not address:
            return ""
        name = self.reader.cstring(self.reader.pointer(address + 16))
        namespace = self.reader.cstring(self.reader.pointer(address + 24))
        return f"{namespace}.{name}" if namespace else name
