"""Write aclopi/agent/data/plant_context.json from the model (aclopi.agent.sequencing_context.read_plant).

Run it again after changing model/Paper.nlogo; tests/test_sequencing.py fails while the file differs
from the model.

    python scripts/a4/export_plant_context.py
"""

from __future__ import annotations

import json
import logging
import sys

from aclopi.agent.sequencing_context import PLANT_FILE, read_plant
from aclopi.sim import SimulationSession


def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    with SimulationSession() as session:
        plant = read_plant(session)
    PLANT_FILE.parent.mkdir(parents=True, exist_ok=True)
    PLANT_FILE.write_text(json.dumps(plant, indent=1) + "\n", encoding="utf-8")
    print(f"written {PLANT_FILE}")
    print(json.dumps({k: plant[k] for k in ("entry", "time_step", "stochastic_extra", "load_unload_machine")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
