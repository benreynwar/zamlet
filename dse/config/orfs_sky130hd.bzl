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
    if target_name == "ALU_default":
        return {
            "PLACE_DENSITY": "0.65",
            "CORE_UTILIZATION": "60",
            # Target-specific parameters for ALU_default can go here
        }
    elif target_name == "ALURS_default":
        return {
            "PLACE_DENSITY": "0.65",
            "CORE_UTILIZATION": "55",
            # Target-specific parameters for ALU_default can go here
        }
    elif target_name == "RegisterFile_default":
        return {
            "PLACE_DENSITY": "0.50",
            "CORE_UTILIZATION": "40",
            # Target-specific parameters for ALU_default can go here
        }
    elif target_name == "RegisterFile_D":
        return {
            "PLACE_DENSITY": "0.50",
            "CORE_UTILIZATION": "40",
            # Target-specific parameters for ALU_default can go here
        }
    elif target_name == "RegisterFile_A":
        return {
            "PLACE_DENSITY": "0.65",
            "CORE_UTILIZATION": "55",
            # Target-specific parameters for ALU_default can go here
        }
    elif target_name == "RegisterFile_P":
        return {
            "PLACE_DENSITY": "0.65",
            "CORE_UTILIZATION": "55",
            # Target-specific parameters for ALU_default can go here
        }
    elif target_name == "RegisterFileAndRename_default":
        return {
            "PLACE_DENSITY": "0.43",
            "CORE_UTILIZATION": "40",
            # Target-specific parameters for ALU_default can go here
        }
    else:
        # No specific overrides for this target
        return {}
