set mxu_backward_inputs [get_ports {
    io_ewBackwardInput_*
    io_nsBackwardInput_*
}]

set mxu_backward_outputs [get_ports {
    io_ewBackwardOutput_*
    io_nsBackwardOutput_*
}]

set mxu_forward_inputs [get_ports {
    io_ewForwardInput_*
    io_nsForwardInput_*
}]

set mxu_forward_outputs [get_ports {
    io_ewForwardOutput_*
    io_nsForwardOutput_*
}]

set mxu_memory_outputs [get_ports {
    io_cToMemory_*
    io_cToMemoryValid_*
}]

set mxu_error_outputs [get_ports {
    io_error
}]

set mxu_backward_input_delay_pct 70
set mxu_backward_input_delay_value [expr $::env(CLOCK_PERIOD) * $mxu_backward_input_delay_pct / 100]
puts "\[INFO] Setting JamletMxu signoff backward input delay to: $mxu_backward_input_delay_value"
set_input_delay $mxu_backward_input_delay_value -clock $clocks $mxu_backward_inputs

set mxu_backward_output_delay_pct 60
set mxu_backward_output_delay_value [expr $::env(CLOCK_PERIOD) * $mxu_backward_output_delay_pct / 100]
puts "\[INFO] Setting JamletMxu signoff backward output delay to: $mxu_backward_output_delay_value"
set_output_delay $mxu_backward_output_delay_value -clock $clocks $mxu_backward_outputs

set mxu_forward_input_delay_pct 70
set mxu_forward_input_delay_value [expr $::env(CLOCK_PERIOD) * $mxu_forward_input_delay_pct / 100]
puts "\[INFO] Setting JamletMxu signoff forward input delay to: $mxu_forward_input_delay_value"
set_input_delay $mxu_forward_input_delay_value -clock $clocks $mxu_forward_inputs

set mxu_forward_output_delay_pct 60
set mxu_forward_output_delay_value [expr $::env(CLOCK_PERIOD) * $mxu_forward_output_delay_pct / 100]
puts "\[INFO] Setting JamletMxu signoff forward output delay to: $mxu_forward_output_delay_value"
set_output_delay $mxu_forward_output_delay_value -clock $clocks $mxu_forward_outputs

set mxu_memory_output_delay_pct 60
set mxu_memory_output_delay_value [expr $::env(CLOCK_PERIOD) * $mxu_memory_output_delay_pct / 100]
puts "\[INFO] Setting JamletMxu signoff memory output delay to: $mxu_memory_output_delay_value"
set_output_delay $mxu_memory_output_delay_value -clock $clocks $mxu_memory_outputs

set mxu_error_output_delay_pct 60
set mxu_error_output_delay_value [expr $::env(CLOCK_PERIOD) * $mxu_error_output_delay_pct / 100]
puts "\[INFO] Setting JamletMxu signoff error output delay to: $mxu_error_output_delay_value"
set_output_delay $mxu_error_output_delay_value -clock $clocks $mxu_error_outputs
