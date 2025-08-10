# ORFS Parameter Configuration System
# Hierarchical parameter loading: orfs.bzl -> orfs_{pdk}.bzl (which handles target overrides)

load("//dse:config/orfs.bzl", "ORFS_BASE_ARGS")
load("//dse:config/orfs_sky130hd.bzl", "get_sky130hd_orfs_args")
load("//dse:config/orfs_asap7.bzl", "get_asap7_orfs_args")

def get_orfs_arguments(target_name, pdk, experiment = "standard"):
    """
    Get ORFS arguments dictionary for a target, PDK, and experiment.
    
    Loads and merges parameters from hierarchical Bazel configuration files:
    1. Base defaults from orfs.bzl
    2. PDK-specific config (which handles its own target overrides)
    3. Experiment-specific overrides
    
    Args:
        target_name: The target component name (e.g., "ALU_default")
        pdk: The PDK name (e.g., "sky130hd", "asap7")
        experiment: The experiment tag (e.g., "standard", "high_density", default: "standard")
        
    Returns:
        Dictionary of merged ORFS arguments
    """
    
    # Start with base configuration
    merged_args = dict(ORFS_BASE_ARGS)
    
    # Let PDK-specific config handle everything else (including target overrides)
    if pdk == "sky130hd":
        pdk_args = get_sky130hd_orfs_args(target_name)
    elif pdk == "asap7":
        pdk_args = get_asap7_orfs_args(target_name)
    else:
        fail("Unsupported PDK: {}. Expected 'sky130hd' or 'asap7'.".format(pdk))
    
    merged_args.update(pdk_args)
    return merged_args