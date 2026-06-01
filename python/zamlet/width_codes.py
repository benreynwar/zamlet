from enum import IntEnum


class ElementWidthCode(IntEnum):
    EW1 = 0
    EW8 = 3
    EW16 = 4
    EW32 = 5
    EW64 = 6
    EW128 = 7
    EW256 = 8
    EW512 = 9


class WidthFormatCode(IntEnum):
    WF1 = 0
    WF2 = 1
    WF4 = 2
    WF8 = 3
    WF16 = 4
    WF32 = 5
    WF64 = 6
    WF128 = 7
    WF256 = 8
    WF512 = 9


_EW_BY_WIDTH = {
    1: ElementWidthCode.EW1,
    8: ElementWidthCode.EW8,
    16: ElementWidthCode.EW16,
    32: ElementWidthCode.EW32,
    64: ElementWidthCode.EW64,
    128: ElementWidthCode.EW128,
    256: ElementWidthCode.EW256,
    512: ElementWidthCode.EW512,
}

_WF_BY_WIDTH = {
    1: WidthFormatCode.WF1,
    2: WidthFormatCode.WF2,
    4: WidthFormatCode.WF4,
    8: WidthFormatCode.WF8,
    16: WidthFormatCode.WF16,
    32: WidthFormatCode.WF32,
    64: WidthFormatCode.WF64,
    128: WidthFormatCode.WF128,
    256: WidthFormatCode.WF256,
    512: WidthFormatCode.WF512,
}


def ew_code(width_bits: int) -> ElementWidthCode:
    return _EW_BY_WIDTH[width_bits]


def wf_code(width_bits: int) -> WidthFormatCode:
    return _WF_BY_WIDTH[width_bits]
