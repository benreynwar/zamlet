def jamlet_mxu_top(n, ew_loop, ns_loop, csa, bc, de, backward_reg, split_drain, reset_group):
    return "JamletMxu{}x{}_EwLoop{}_NsLoop{}_CSA{}_BC{}_DE{}_BackwardReg{}_SplitDrain{}_ResetGroup{}".format(
        n,
        n,
        1 if ew_loop else 0,
        1 if ns_loop else 0,
        1 if csa else 0,
        1 if bc else 0,
        1 if de else 0,
        1 if backward_reg else 0,
        1 if split_drain else 0,
        reset_group,
    )
