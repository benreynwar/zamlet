import argparse
import json
import re
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--power-report", type=Path, required=True)
    parser.add_argument("--clock-period-ns", type=float, required=True)
    parser.add_argument("--target-utilization", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    metrics = json.loads(args.state.read_text())["metrics"]
    total_match = re.search(
        r"^Total\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)",
        args.power_report.read_text(),
        flags=re.MULTILINE,
    )
    if total_match is None:
        raise ValueError("Nominal power report has no Total row")
    internal, switching, leakage, total = map(float, total_match.groups())

    result = {
        "clock_period_ns": args.clock_period_ns,
        "target_utilization_percent": args.target_utilization,
        "area_um2": {
            "instances": metrics["design__instance__area"],
            "core": metrics["design__core__area"],
            "die": metrics["design__die__area"],
        },
        "actual_utilization": metrics["design__instance__utilization"],
        "routing": {
            "drc_errors": metrics["route__drc_errors"],
            "wirelength_um": metrics["route__wirelength"],
        },
        "electrical": {
            "max_cap_violations": metrics["design__max_cap_violation__count"],
            "max_slew_violations": metrics["design__max_slew_violation__count"],
        },
        "timing_ns": {
            "setup_worst_slack": metrics["timing__setup__ws"],
            "hold_worst_slack": metrics["timing__hold__ws"],
        },
        "nominal_power_w": {
            "internal": internal,
            "switching": switching,
            "leakage": leakage,
            "total": total,
        },
    }
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
