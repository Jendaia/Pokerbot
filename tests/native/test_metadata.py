from pathlib import Path
import struct
import tempfile
import unittest

from texasholdem.analyzers.native.metadata import Metadata


def metadata_bytes():
    # One enum with ordinary and negative defaults; no proprietary metadata.
    strings = b"\0Suit\0Cards\0value__\0CLUBS\0NONE\0"
    type_values = [1, 6, 0, -1, -1, -1, -1, 0, 0, -1, -1, -1, -1, -1, -1, -1]
    type_values += [0, 0, 3, 0, 0, 0, 0, 0, 2, 0x02000001]
    types = struct.pack("<16i8H2I", *type_values)
    fields = b"".join(struct.pack("<IiI", strings.index(name), 0, 0x04000001 + index)
                      for index, name in enumerate((b"value__", b"CLUBS", b"NONE")))
    defaults = struct.pack("<iii", 1, 0, 0) + struct.pack("<iii", 2, 0, 1)
    values = b"\x02\x01"  # 1 and -1 in signed compressed form
    header = [0] * 64
    header[:2] = [0xFAB11BAF, 31]
    data = bytearray(256)
    for offset_index, section in ((6, strings), (24, fields), (40, types), (16, defaults), (18, values)):
        header[offset_index:offset_index + 2] = [len(data), len(section)]
        data.extend(section)
    struct.pack_into("<64I", data, 0, *header)
    return data


class MetadataTests(unittest.TestCase):
    def read_metadata(self, data):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "global-metadata.dat"
            file.write_bytes(data)
            return Metadata(file)

    def test_type_field_and_enum_resolution(self):
        data = self.read_metadata(metadata_bytes())
        self.assertEqual(data.types[0].full_name, "Cards.Suit")
        self.assertEqual([f.name for f in data.fields(data.types[0])], ["value__", "CLUBS", "NONE"])
        self.assertEqual(data.enum_values("Cards.Suit"), {1: "CLUBS", -1: "NONE"})
        self.assertEqual(data.enum_values(data.types[0]), {1: "CLUBS", -1: "NONE"})

    def test_invalid_metadata_rejected(self):
        for data in (b"bad", metadata_bytes()[:260]):
            with self.assertRaises(ValueError):
                self.read_metadata(data)
        for index, value in ((0, 0), (1, 99), (7, 1_000_000), (17, 13), (25, 13), (41, 89)):
            data = metadata_bytes()
            struct.pack_into("<I", data, index * 4, value)
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.read_metadata(data)

    def test_all_compressed_integer_widths_and_sign(self):
        cases = ((b"\x02", 1), (b"\x01", -1), (b"\x80\x80", 64),
                 (b"\xc0\x00\x80\x00", 16384), (b"\xf0\xfc\xff\xff\xff", 2147483646),
                 (b"\xff", -2147483648), (b"\xfe", 2147483647))
        for data, expected in cases:
            self.assertEqual(Metadata.compressed_integer(data, 0), expected)
        for data in (b"", b"\x80", b"\xc0\x00", b"\xf0\x00", b"\xe0\x00\x00\x00\x00"):
            with self.assertRaises(ValueError):
                Metadata.compressed_integer(data, 0)
