import ctypes
import importlib.util
import os
import struct
import sys
import unittest

from texasholdem.analyzers.native.collections import array_integers, array_pointers, list_pointers
from texasholdem.analyzers.native.memory import MemoryReader, MemoryRegion


class ByteMemory:
    def __init__(self):
        self.data = bytearray(4096)

    def read(self, address, size):
        if not 0 <= address <= address + size <= len(self.data):
            raise OSError("Unmapped test address")
        return bytes(self.data[address:address + size])

    def unpack(self, fmt, address):
        return struct.unpack(fmt, self.read(address, struct.calcsize(fmt)))

    def pointer(self, address):
        return self.unpack("<Q", address)[0]

    def write(self, fmt, address, *values):
        struct.pack_into(fmt, self.data, address, *values)


class CollectionsTests(unittest.TestCase):
    def setUp(self):
        self.memory = ByteMemory()
        self.memory.write("<Qii", 128 + 16, 256, 2, 1)
        self.memory.write("<Q", 256 + 24, 4)
        self.memory.write("<QQQQ", 256 + 32, 512, 768, 0, 0)

    def test_capacity_does_not_add_unused_players(self):
        self.assertEqual(list_pointers(self.memory, 128), (512, 768))
        self.assertEqual(array_pointers(self.memory, 256), (512, 768, 0, 0))
        self.assertEqual(list_pointers(self.memory, 0), ())
        self.memory.write("<Qiii", 1024 + 24, 3, 1, 3, 5)
        self.assertEqual(array_integers(self.memory, 1024), (1, 3, 5))

    def test_invalid_sizes_and_missing_arrays_rejected(self):
        self.memory.write("<i", 128 + 24, 5)
        with self.assertRaises(ValueError):
            list_pointers(self.memory, 128)
        self.memory.write("<Q", 128 + 16, 0)
        with self.assertRaises(ValueError):
            list_pointers(self.memory, 128)
        with self.assertRaises(ValueError):
            array_pointers(self.memory, 256, maximum=3)

    def test_mutating_list_rejected(self):
        original = self.memory.read

        def changing_read(address, size):
            data = original(address, size)
            if address == 256 + 32:
                self.memory.write("<i", 128 + 28, 2)
            return data

        self.memory.read = changing_read
        with self.assertRaisesRegex(ValueError, "changed"):
            list_pointers(self.memory, 128)


@unittest.skipUnless(sys.platform == "linux", "Linux /proc memory reader")
class ProcessMemoryTests(unittest.TestCase):
    def test_read_only_memory_and_utf16_string(self):
        import fcntl
        raw = "A😎".encode("utf-16-le")
        data = b"\0" * 16 + struct.pack("<i", len(raw) // 2) + raw
        buffer = ctypes.create_string_buffer(data)
        with MemoryReader(os.getpid()) as reader:
            self.assertEqual(fcntl.fcntl(reader.fd, fcntl.F_GETFL) & os.O_ACCMODE, os.O_RDONLY)
            self.assertEqual(reader.managed_string(ctypes.addressof(buffer)), "A😎")
            self.assertIsNone(reader.managed_string(0))
            for address, size in ((-1, 1), (1, -1), (2 ** 63, 1), (1, 100_000_000)):
                with self.assertRaises(ValueError):
                    reader.read(address, size)
        self.assertEqual(reader.fd, -1)

    @unittest.skipUnless(importlib.util.find_spec("numpy"), "Optional NumPy scanner")
    def test_pointer_scan_returns_aligned_matches_only(self):
        buffer = ctypes.create_string_buffer(struct.pack("<QQQQ", 123, 456, 123, 789))
        start = ctypes.addressof(buffer)
        with MemoryReader(os.getpid()) as reader:
            reader.regions = (MemoryRegion(start, start + 32, "rw-p", 0, ""),)
            self.assertEqual(reader.find_pointers({123, 789}), {123: [start, start + 16], 789: [start + 24]})
