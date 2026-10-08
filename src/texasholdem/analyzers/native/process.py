from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PokeristProcess:
    pid: int
    installation: Path
    metadata: Path


def find_processes(pid: int | None = None) -> tuple[PokeristProcess, ...]:
    """Find the game through its process name and installation, not Steam helpers."""
    directories = [Path(f"/proc/{pid}")] if pid else list(Path("/proc").iterdir())
    result = []
    for directory in directories:
        if not directory.name.isdigit():
            continue
        try:
            name = (directory / "comm").read_text().strip()
            if "texas poker" not in name.lower():
                continue
            installation = (directory / "cwd").resolve(strict=True)
            metadata = installation / "Texas Poker_Data/il2cpp_data/Metadata/global-metadata.dat"
            if metadata.is_file() and (installation / "GameAssembly.dll").is_file():
                result.append(PokeristProcess(int(directory.name), installation, metadata))
        except (OSError, RuntimeError):
            continue
    return tuple(result)


def find_process(pid: int | None = None) -> PokeristProcess:
    processes = find_processes(pid)
    if len(processes) != 1:
        raise ValueError("Start Pokerist and enter a table; use --pid if multiple clients are running")
    return processes[0]
