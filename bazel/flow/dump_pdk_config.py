#!/usr/bin/env python3
"""Dump PDK configuration variables as JSON.

This script loads PDK and SCL configuration using librelane's Config
class and outputs the configuration as JSON. This is used by the
Bazel repository rule to generate PDK config at fetch time.

Usage:
    python dump_pdk_config.py --pdk-root /path/to/pdks --pdk sky130A --scl sky130_fd_sc_hd
"""

import argparse
import json
import sys
from decimal import Decimal
from typing import Any, Dict


def custom_encoder(obj):
    """JSON encoder that handles librelane types."""
    if isinstance(obj, Decimal):
        return float(obj)
    # Handle librelane's Path type
    if hasattr(obj, '__fspath__'):
        return str(obj)
    # Handle Path-like objects
    if hasattr(obj, 'as_posix'):
        return obj.as_posix()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def get_all_pdk_variables():
    """Collect all PDK variables from flow config and all registered steps."""
    from librelane.config.flow import pdk_variables, scl_variables
    # Import all steps to register them in the factory
    import librelane.steps
    from librelane.steps import Step

    # Start with flow-level PDK variables
    all_vars = list(pdk_variables) + list(scl_variables)
    seen_names = {v.name for v in all_vars}

    # Collect step-specific PDK variables
    for step_id in Step.factory.list():
        step_cls = Step.factory.get(step_id)
        if step_cls is None:
            continue
        for var in step_cls.config_vars:
            if var.pdk and var.name not in seen_names:
                all_vars.append(var)
                seen_names.add(var.name)

    return all_vars


def load_pdk_config(pdk_root: str, pdk: str, scl: str) -> Dict[str, Any]:
    """Load PDK and SCL configuration using librelane.

    Uses librelane's full config processing including:
    - PDK compatibility migrations (old variable names)
    - Variable processing with deprecated name handling
    - Type coercion
    """
    from librelane.config import Config

    # Get all PDK variables (flow-level + step-specific)
    all_pdk_vars = get_all_pdk_variables()

    # Get fully processed config using librelane's internal method
    # This handles deprecated names, type coercion, etc.
    processed, _pdkpath, _scl = Config._Config__get_pdk_config(
        pdk=pdk,
        scl=scl,
        pdk_root=pdk_root,
        flow_pdk_vars=all_pdk_vars,
    )
    return dict(processed)


def main():
    parser = argparse.ArgumentParser(description="Dump PDK configuration as JSON")
    parser.add_argument("--pdk-root", required=True, help="PDK root directory")
    parser.add_argument("--pdk", required=True, help="PDK name (e.g., sky130A)")
    parser.add_argument("--scl", required=True, help="Standard cell library name")
    parser.add_argument("--output", "-o", help="Output file (default: stdout)")
    args = parser.parse_args()

    try:
        config = load_pdk_config(args.pdk_root, args.pdk, args.scl)

        # Output as JSON
        output = json.dumps(config, indent=2, default=custom_encoder)

        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
        else:
            print(output)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
