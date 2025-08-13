# ASAP7 PDK-specific ORFS parameter configuration

# PDK-level overrides
_ASAP7_OVERRIDES = {
    "ABC_CLOCK_PERIOD_IN_PS": "1000",  # 1000ps = 1ns clock period
    "SETUP_SLACK_MARGIN": "-10000",   # Setup slack margin in ps
}

def get_asap7_orfs_args(target_name):
    """
    Get ASAP7-specific ORFS arguments, including target-specific overrides.
    
    Args:
        target_name: The target component name (e.g., "ALU_default")
        
    Returns:
        Dictionary of PDK and target-specific ORFS overrides
    """
    
    # Start with PDK-level overrides
    args = dict(_ASAP7_OVERRIDES)
    
    # Add target-specific overrides
    target_overrides = _get_target_overrides(target_name)
    args.update(target_overrides)
    
    return args

def _get_target_overrides(target_name):
    """Get target-specific overrides for ASAP7 PDK."""
    if target_name == "ALU_default":
        return {}
    else:
        # No specific overrides for this target - uses defaults (0.6/0.6)
        return {}
