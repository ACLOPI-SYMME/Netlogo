"""Prints the container's CPU topology and limits (Linux only)."""

from __future__ import annotations

import json
from pathlib import Path

from common import CGROUP, environment_info


def main() -> None:
    info = environment_info()
    model = next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                  if line.startswith("model name")), "?")
    all_cpus = sorted(int(p.name[3:]) for p in Path("/sys/devices/system/cpu").glob("cpu[0-9]*"))
    siblings = {c: Path(f"/sys/devices/system/cpu/cpu{c}/topology/thread_siblings_list").read_text().strip() for c in all_cpus}
    core_ids = {c: Path(f"/sys/devices/system/cpu/cpu{c}/topology/core_id").read_text().strip() for c in all_cpus}
    print(json.dumps({
        **info,
        "cpu_model": model,
        "host_cpus": len(all_cpus),
        "siblings_all": siblings,
        "core_id_all": core_ids,
        "cpu.max": (CGROUP / "cpu.max").read_text().strip(),
        "memory.max": (CGROUP / "memory.max").read_text().strip(),
        "memory.swap.max": (CGROUP / "memory.swap.max").read_text().strip() if (CGROUP / "memory.swap.max").exists() else None,
    }, indent=1))


if __name__ == "__main__":
    main()
