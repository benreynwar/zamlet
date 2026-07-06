def recombine_latency(
    register_input: bool,
    register_carry_save_output: bool,
    register_final_adder_middle: bool,
    register_output: bool,
) -> int:
    return (
        int(register_input)
        + int(register_carry_save_output)
        + int(register_final_adder_middle)
        + int(register_output)
    )


def latency(
    width: int,
    min_width: int = 8,
    register_input: bool = True,
    register_leaf_input: bool = True,
    recombine_buffer_min_width: int = 32,
    recombine_final_adder_buffer_min_width: int = 128,
    register_output: bool = True,
) -> int:
    input_latency = int(register_input)
    output_latency = int(register_output)

    if width == min_width:
        internal_latency = 0
    else:
        half_width = width // 2
        internal_latency = latency(
            half_width,
            min_width=min_width,
            register_input=register_leaf_input and half_width == min_width,
            register_leaf_input=register_leaf_input,
            recombine_buffer_min_width=recombine_buffer_min_width,
            recombine_final_adder_buffer_min_width=recombine_final_adder_buffer_min_width,
            register_output=True,
        ) + recombine_latency(
            register_input=False,
            register_carry_save_output=width >= recombine_buffer_min_width,
            register_final_adder_middle=2 * width >= recombine_final_adder_buffer_min_width,
            register_output=False,
        )

    return input_latency + internal_latency + output_latency
