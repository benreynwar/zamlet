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

set mxu_backward_input_delay_pct 60
set mxu_backward_input_delay_value [expr $::env(CLOCK_PERIOD) * $mxu_backward_input_delay_pct / 100]
puts "\[INFO] Setting JamletMxu backward input delay to: $mxu_backward_input_delay_value"
set_input_delay $mxu_backward_input_delay_value -clock $clocks $mxu_backward_inputs

set mxu_backward_output_delay_pct 60
set mxu_backward_output_delay_value [expr $::env(CLOCK_PERIOD) * $mxu_backward_output_delay_pct / 100]
puts "\[INFO] Setting JamletMxu backward output delay to: $mxu_backward_output_delay_value"
set_output_delay $mxu_backward_output_delay_value -clock $clocks $mxu_backward_outputs

set mxu_forward_input_delay_pct 60
set mxu_forward_input_delay_value [expr $::env(CLOCK_PERIOD) * $mxu_forward_input_delay_pct / 100]
puts "\[INFO] Setting JamletMxu forward input delay to: $mxu_forward_input_delay_value"
set_input_delay $mxu_forward_input_delay_value -clock $clocks $mxu_forward_inputs

set mxu_forward_output_delay_pct 60
set mxu_forward_output_delay_value [expr $::env(CLOCK_PERIOD) * $mxu_forward_output_delay_pct / 100]
puts "\[INFO] Setting JamletMxu forward output delay to: $mxu_forward_output_delay_value"
set_output_delay $mxu_forward_output_delay_value -clock $clocks $mxu_forward_outputs
