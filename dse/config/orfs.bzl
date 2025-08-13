# Base ORFS configuration parameters
# These are the default parameters used for all targets, overridden by PDK and target-specific configs

ORFS_BASE_ARGS = {
    "FILL_CELLS": "",
    "TAPCELL_TCL": "",
    "SKIP_REPORT_METRICS": "1",
    "SKIP_CTS_REPAIR_TIMING": "1",
    "SKIP_INCREMENTAL_REPAIR": "1",
    "GND_NETS_VOLTAGES": "",
    "PWR_NETS_VOLTAGES": "",
    "GPL_ROUTABILITY_DRIVEN": "1",
    "GPL_TIMING_DRIVEN": "0",
    "SETUP_SLACK_MARGIN": "-10000",
    "TNS_END_PERCENT": "0",
    "SYNTH_HIERARCHICAL": "1",
    "SYNTH_MINIMUM_KEEP_SIZE": "50",
    "SYNTH_MEMORY_MAX_BITS": "8192",
    "PLACE_DENSITY": "0.55",
    "CORE_UTILIZATION": "50",
    "io_input_delay_fraction": "0.6",
    "io_output_delay_fraction": "0.6",
}
