from dataclasses import dataclass
from fmvpu.bamlet.bamlet_interface import BamletInterface
from fmvpu.bamlet.bamlet_params import BamletParams
from fmvpu.amlet import packet_utils
from fmvpu.amlet.alu_lite_instruction import ALULiteInstruction, ALULiteModes
from fmvpu.amlet.predicate_instruction import PredicateInstruction, PredicateModes, Src1Mode
from fmvpu.amlet.alu_instruction import ALUInstruction
from fmvpu.amlet.packet_instruction import PacketInstruction, PacketModes
from fmvpu.amlet.control_instruction import ControlInstruction, ControlModes
from fmvpu.amlet.ldst_instruction import LoadStoreInstruction, LoadStoreModes
from fmvpu.amlet.instruction import VLIWInstruction

@dataclass
class ReceiveKernelRegs:
    # Global Bamlet Config
    g_words_per_amlet: int = 2
    g_amlet_columns_minus_one: int = 3

    # Global Amlet Config
    a_base_address: int = 1
    a_words_per_row: int = 4

    # Local config
    # The coords of the amlet we'er sending to
    a_local_column_minus_one: int = 6
    a_local_column: int = 5

    # Working registeres
    a_outer_index: int = 7
    a_inner_index: int = 8
    a_address: int = 9
    p_condition: int = 1
    d_working: int = 1


@dataclass
class ReceiveKernelArgs:
    g_words_per_amlet: int
    g_amlet_columns_minus_one: int
    a_base_address: int
    a_words_per_row: int
    a_local_column_minus_one: list[int]
    a_local_column: list[int]


def send_data(bi: BamletInterface, side, data, channel=0):
    '''
    Sends data to the bamlet in the form that the receive kernel expects
    '''
    assert side in ('n', 's', 'e', 'w')
    side_length = bi.params.n_amlet_columns if side in ('n', 's') else bi.params.n_amlet_rows
    # Make a packet for each sender
    assert len(data) % bi.params.n_amlets == 0
    packets = []
    # For each column/row we need a packet header.
    # The target is the last amlet in that column/row (we broadcast it there)
    for index in range(side_length):
        if side == 's':
            target = (bi.bamlet_x+index, bi.bamlet_y)
        elif side == 'n':
            target = (bi.bamlet_x+index, bi.bamlet_y+bi.params.n_amlet_rows-1)
        elif side == 'w':
            target = (bi.bamlet_x+bi.params.n_amlet_columns-1, bi.bamlet_y + index)
        elif side == 'e':
            target = (bi.bamlet_x, bi.bamlet_y + index)
        else:
            assert False
        assert len(data) % side_length == 0
        header = packet_utils.PacketHeader(
            length=len(data)//side_length,
            dest_x=target[0],
            dest_y=target[1],
            is_broadcast=True,
            )
        packet = [header.encode()] + data[index::side_length]
        driver = bi.drivers[(side, index, channel)]
        driver.add_packet(packet)


def make_receive_kernel_args(params: BamletParams, base_address, n, side):
    """
    Args:
      base_x, base_y: The coords of the upper left of the bamlet.
      side: The side the data is arriving from.
    """

    assert side in ('w', 'e', 'n', 's')
    local_columns = []
    for offset_y in range(params.n_amlet_rows):
        for offset_x in range(params.n_amlet_columns):
            local_columns.append(offset_x)
    local_columns_minus_one = [x-1 for x in local_columns]
    local_columns_minus_one[0] = params.n_amlet_columns  # Sholdn't get used.

    args = ReceiveKernelArgs(
        g_words_per_amlet=n//params.n_amlets,
        g_amlet_columns_minus_one=params.n_amlet_columns-1,
        a_base_address=base_address,
        a_words_per_row=n//params.n_amlet_rows,
        a_local_column_minus_one=local_columns_minus_one,
        a_local_column=local_columns,
        )

    return args



def receive_kernel(params: BamletParams, regs: ReceiveKernelRegs, side, channel):
    """
    Each row of amlets receives a packet.

    The addressing of amlets is
    0  1  2  3
    4  5  6  7
    8  9 10 11

    If we sent in a vector of length 36 then amlet 0 would
    get the 0th, 12th and 24th entires.
    Amlet 1 would get 1st, 13th and 25th entries and so on.

    This means that the packet to the first row should contain
    0, 1, 2, 3, 12, 13, 14, 15, 24, 25, 26, 27

    Maybe it's not reasonable to expect the data to arrive like that
    but it's what this kernel assumes.

    """
    assert side in ('n', 's', 'e', 'w')
    assert 0 <= channel < params.amlet.n_channels

    # The first instruction is a Receive
    # It does a loop based on the length on the n/n_amlets
    # Inside another loop based on the number of amlet columns
    # When the inner loop index matches it's local column then it
    # stores the value in the base address + outer loop index.

    # addr = base_addr
    # Loop n/n_amlets -> outer_index
    #   addr = addr + 1
    #   Loop n_amlet_columns -> inner_index
    #     x = GetWord
    #     If inner_index == local_column
    #       x -> Store(addr)
    #     Endif
    #   Endloop
    # Endloop

    # With VLIW that would look like

    # addr = base_addr
    # Loop n/n_amlets -> outer_index      | addr = addr + 1     |
    # Loop n_amlet_columns -> inner_index | x = GetWord         |  a = inner_index == local_column 
    # If a                                | x -> Store(addr)    |  endif/endloop
    #                                                           |  endloop

    # We could give the loop a 'length' argument to remove the endloop.
    # Then in the hot loop we have 5 used slots in 2 instructions so 2.5 / cycle.
    # I think a four-instruction dispatch solution could do twices as fast.

    # I'd like to make a multi-dispatch and compare it to the VLIW solution.

    # I'll write the kernels so that it's a sequence of instructions, and then have a function
    # that packs them into VLIW instructions.  That way we can run the same kernel on both.

    instrs = []
    instrs.append(PacketInstruction(
        mode=PacketModes.RECEIVE,
        a_dst=regs.a_words_per_row,
        ))
    # addr = base_addr-1
    # We subtract 1 because we'll add one in the loop before using
    # it the first time.
    instrs.append(ALULiteInstruction(
        mode=ALULiteModes.SUBI,
        src1=regs.a_base_address,
        src2=1,
        a_dst=regs.a_address,
        ))
    # Loop n/n_amlets -> outer_index
    instrs.append(ControlInstruction(
        mode=ControlModes.LOOP_GLOBAL,
        iterations=regs.g_words_per_amlet,
        dst=regs.a_outer_index,
        ))
    #     If inner_index == local_column
    instrs.append(PredicateInstruction(
        mode=PredicateModes.EQ,
        src1_mode=Src1Mode.IMMEDIATE,
        src1_value=0,
        src2=regs.a_local_column,
        dst=regs.p_condition,
        ))
    #     x = GetWord
    instrs.append(PacketInstruction(
        mode=PacketModes.GET_WORD,
        d_dst=regs.d_working,
        ))
    #   addr = addr + 1
    instrs.append(ALULiteInstruction(
        mode=ALULiteModes.ADDI,
        src1=regs.a_address,
        src2=1,
        a_dst=regs.a_address,
        ))
    #       x -> Store(addr)
    instrs.append(LoadStoreInstruction(
        mode=LoadStoreModes.STORE,
        d_reg=regs.d_working,
        addr=regs.a_address,
        predicate=regs.p_condition,
        ))
    #   Loop n_amlet_columns -> inner_index
    instrs.append(ControlInstruction(
        mode=ControlModes.LOOP_GLOBAL,
        iterations=regs.g_amlet_columns_minus_one,
        dst=regs.a_inner_index,
        ))
    #     If inner_index == local_column
    instrs.append(PredicateInstruction(
        mode=PredicateModes.EQ,
        src1_mode=Src1Mode.LOOP_INDEX,
        src1_value=1, # Loop level 1 (inner index)
        src2=regs.a_local_column_minus_one,
        dst=regs.p_condition,
        ))
    #     x = GetWord
    instrs.append(PacketInstruction(
        mode=PacketModes.GET_WORD,
        d_dst=regs.d_working,
        ))
    #       x -> Store(addr)
    instrs.append(LoadStoreInstruction(
        mode=LoadStoreModes.STORE,
        d_reg=regs.d_working,
        addr=regs.a_address,
        predicate=regs.p_condition,
        ))
    instrs.append(ControlInstruction(mode=ControlModes.END_LOOP))
    instrs.append(ControlInstruction(mode=ControlModes.END_LOOP))
    instrs.append(ControlInstruction(mode=ControlModes.HALT))

    return instrs
