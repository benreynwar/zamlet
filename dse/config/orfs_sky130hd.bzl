# Sky130HD PDK-specific ORFS parameter configuration

# PDK-level overrides
_SKY130HD_OVERRIDES = {
    "PLACE_DENSITY": "0.60",
    "CORE_UTILIZATION": "30",
}

def get_sky130hd_orfs_args(target_name):
    """
    Get Sky130HD-specific ORFS arguments, including target-specific overrides.
    
    Args:
        target_name: The target component name (e.g., "ALU_default")
        
    Returns:
        Dictionary of PDK and target-specific ORFS overrides
    """
    
    # Start with PDK-level overrides
    args = dict(_SKY130HD_OVERRIDES)
    
    # Add target-specific overrides
    target_overrides = _get_target_overrides(target_name)
    args.update(target_overrides)
    
    return args

def _get_target_overrides(target_name):
    """Get target-specific overrides for Sky130HD PDK."""
    if target_name == "Amlet_default":
        return {
            "PLACE_DENSITY": "0.43",
            "CORE_UTILIZATION": "40",
        }
    elif target_name == "ALU_default":
        return {
            "PLACE_DENSITY": "0.65",
            "CORE_UTILIZATION": "60",
        }
    elif target_name == "ALURS_default":
        return {
            "PLACE_DENSITY": "0.53",
            "CORE_UTILIZATION": "50",
            "io_input_delay_fraction": "0.7",
            "io_output_delay_fraction": "0.6",
        }
    elif target_name == "RegisterFile_default":
        return {
            "PLACE_DENSITY": "0.50",
            "CORE_UTILIZATION": "40",
        }
    elif target_name == "RegisterFile_D":
        return {
            "PLACE_DENSITY": "0.50",
            "CORE_UTILIZATION": "40",
        }
    elif target_name == "RegisterFile_A":
        return {
            "PLACE_DENSITY": "0.65",
            "CORE_UTILIZATION": "55",
        }
    elif target_name == "RegisterFile_P":
        return {
            "PLACE_DENSITY": "0.65",
            "CORE_UTILIZATION": "55",
        }
    elif target_name == "RegisterFileAndRename_default":
        return {
            "PLACE_DENSITY": "0.43",
            "CORE_UTILIZATION": "40",
            "io_input_delay_fraction": "0.6",
            "io_output_delay_fraction": "0.5",
        }
    elif target_name == "NetworkNode_default":
        return {
            "PLACE_DENSITY": "0.58",
            "CORE_UTILIZATION": "55",
        }
    else:
        # No specific overrides for this target
        return {}
