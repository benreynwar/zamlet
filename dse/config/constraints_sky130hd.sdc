set clk_name clock
set clk_port_name clock
set clk_period 10

set sdc_version 2.0

# clk_name, clk_port_name and clk_period are set by the constraints.sdc file
# that includes this generic part.

set clk_port [get_ports $clk_port_name]
create_clock -period $clk_period -waveform [list 0 [expr $clk_period / 2]] -name $clk_name $clk_port

set non_clk_inputs  [lsearch -inline -all -not -exact [all_inputs] $clk_port]
set all_register_outputs [get_pins -of_objects [all_registers] -filter {direction == output}]

# Set input/output delays as 60% of clock period for realistic timing constraints
set io_delay [expr $clk_period * 0.6]

set_input_delay [expr $clk_period * 0.8] -clock $clk_name $non_clk_inputs
set_output_delay [expr $clk_period * 0.3] -clock $clk_name [all_outputs]

# This allows us to view the different groups
# in the histogram in the GUI and also includes these
# groups in the report
group_path -name in2reg -from $non_clk_inputs -to [all_registers]
group_path -name reg2out -from [all_registers] -to [all_outputs]
group_path -name reg2reg -from [all_registers] -to [all_registers]
group_path -name in2out -from $non_clk_inputs -to [all_outputs]
