def sum_stationary_top(n, csa, bc, de, split_drain, reset_group):
    return "SumStationary{}x{}_CSA{}_BC{}_DE{}_SplitDrain{}_ResetGroup{}".format(
        n,
        n,
        1 if csa else 0,
        1 if bc else 0,
        1 if de else 0,
        1 if split_drain else 0,
        reset_group,
    )

def weight_stationary_top(n, reset_group):
    return "WeightStationary{}x{}_ResetGroup{}".format(n, n, reset_group)
