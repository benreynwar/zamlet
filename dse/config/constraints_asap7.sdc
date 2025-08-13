set clk_name clock
set clk_port_name clock
set clk_period 1000

set sdc_version 2.0

# clk_name, clk_port_name and clk_period are set by the constraints.sdc file
# that includes this generic part.

set clk_port [get_ports $clk_port_name]
create_clock -period $clk_period -waveform [list 0 [expr $clk_period / 2]] -name $clk_name $clk_port

set non_clk_inputs  [lsearch -inline -all -not -exact [all_inputs] $clk_port]
set all_register_outputs [get_pins -of_objects [all_registers] -filter {direction == output}]

# Parameterized input/output delays as fractions of clock period (required)
if {![info exists ::env(io_input_delay_fraction)]} {
    error "io_input_delay_fraction not defined - must be set in ORFS config"
}
if {![info exists ::env(io_output_delay_fraction)]} {
    error "io_output_delay_fraction not defined - must be set in ORFS config"
}

set input_delay_fraction $::env(io_input_delay_fraction)
set output_delay_fraction $::env(io_output_delay_fraction)

set input_delay [expr $clk_period * $input_delay_fraction]
set output_delay [expr $clk_period * $output_delay_fraction]

set_input_delay $input_delay -clock $clk_name $non_clk_inputs
set_output_delay $output_delay -clock $clk_name [all_outputs]

# This allows us to view the different groups
# in the histogram in the GUI and also includes these
# groups in the report
group_path -name in2reg -from $non_clk_inputs -to [all_registers]
group_path -name reg2out -from [all_registers] -to [all_outputs]
group_path -name reg2reg -from [all_registers] -to [all_registers]
group_path -name in2out -from $non_clk_inputs -to [all_outputs]

