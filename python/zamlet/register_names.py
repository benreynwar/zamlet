"""RISC-V register name utilities."""

ABI_NAMES = {
    0: 'zero',
    1: 'ra',
    2: 'sp',
    3: 'gp',
    4: 'tp',
    5: 't0',
    6: 't1',
    7: 't2',
    8: 's0',
    9: 's1',
    10: 'a0',
    11: 'a1',
    12: 'a2',
    13: 'a3',
    14: 'a4',
    15: 'a5',
    16: 'a6',
    17: 'a7',
    18: 's2',
    19: 's3',
    20: 's4',
    21: 's5',
    22: 's6',
    23: 's7',
    24: 's8',
    25: 's9',
    26: 's10',
    27: 's11',
    28: 't3',
    29: 't4',
    30: 't5',
    31: 't6',
}

FLOAT_ABI_NAMES = {
    0: 'ft0',
    1: 'ft1',
    2: 'ft2',
    3: 'ft3',
    4: 'ft4',
    5: 'ft5',
    6: 'ft6',
    7: 'ft7',
    8: 'fs0',
    9: 'fs1',
    10: 'fa0',
    11: 'fa1',
    12: 'fa2',
    13: 'fa3',
    14: 'fa4',
    15: 'fa5',
    16: 'fa6',
    17: 'fa7',
    18: 'fs2',
    19: 'fs3',
    20: 'fs4',
    21: 'fs5',
    22: 'fs6',
    23: 'fs7',
    24: 'fs8',
    25: 'fs9',
    26: 'fs10',
    27: 'fs11',
    28: 'ft8',
    29: 'ft9',
    30: 'ft10',
    31: 'ft11',
}


def reg_name(reg_num):
    """Get ABI name for integer register."""
    return ABI_NAMES.get(reg_num, f'x{reg_num}')


def freg_name(reg_num):
    """Get ABI name for floating-point register."""
    return FLOAT_ABI_NAMES.get(reg_num, f'f{reg_num}')
