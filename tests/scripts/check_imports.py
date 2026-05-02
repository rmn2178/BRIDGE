"""Import verification script for BRIDGE modules."""

from __future__ import annotations

import importlib
import sys

MODULES = [
    "shared.models",
    "shared.sharp",
    "sentinel.tools.fhir_snapshot",
    "sentinel.tools.lace_plus",
    "sentinel.tools.risk_mapper",
    "sentinel.main",
    "bridge_agent.a2a_client",
    "bridge_agent.tools.care_plan",
    "bridge_agent.tools.pcp_handoff",
    "bridge_agent.tools.gap_audit",
    "bridge_agent.main",
]


def main() -> int:
    failures = 0
    for module in MODULES:
        try:
            importlib.import_module(module)
            print(f"✅ {module}")
        except (ImportError, ModuleNotFoundError) as exc:
            failures += 1
            print(f"❌ {module}: {exc}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
