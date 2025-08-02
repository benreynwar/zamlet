# Detailed timing reports script for FMVPU DSE
# Generates comprehensive timing analysis reports using OpenSTA

source $::env(SCRIPTS_DIR)/open.tcl

set output_base [file dirname $::env(OUTPUT)]
set target_name $::env(TARGET_NAME)

# Get the clock for timing analysis
set clock [lindex [all_clocks] 0]

# Setup timing reports - worst case paths
report_checks -path_delay max -format full_clock_expanded -group_count 10 > ${output_base}/${target_name}_setup_timing.rpt

# Hold timing reports - best case paths  
report_checks -path_delay min -format full_clock_expanded -group_count 10 > ${output_base}/${target_name}_hold_timing.rpt

# Critical paths with detailed net information
report_checks -path_delay max -fields {slew cap input nets fanout} -format full_clock_expanded -group_count 5 > ${output_base}/${target_name}_critical_paths.rpt

# Unconstrained paths
report_checks -unconstrained > ${output_base}/${target_name}_unconstrained.rpt

# Clock skew analysis
if {[llength [all_clocks]] > 0} {
    report_clock_skew > ${output_base}/${target_name}_clock_skew.rpt
} else {
    # Create empty file if no clocks
    set f [open ${output_base}/${target_name}_clock_skew.rpt w]
    puts $f "No clocks found in design"
    close $f
}

# Worst negative slack summary
report_worst_slack > ${output_base}/${target_name}_slack_summary.rpt

# Timing summary by path groups
foreach group {in2reg reg2out reg2reg in2out} {
    if {$group == "in2reg"} {
        set all_inputs_list [all_inputs]
        set all_registers_list [all_registers]
        set paths [find_timing_paths -from $all_inputs_list -to $all_registers_list -sort_by_slack -group_path_count 5]
    } elseif {$group == "reg2out"} {
        set all_registers_list [all_registers]
        set all_outputs_list [all_outputs]
        set paths [find_timing_paths -from $all_registers_list -to $all_outputs_list -sort_by_slack -group_path_count 5]
    } elseif {$group == "reg2reg"} {
        set all_registers_list [all_registers]
        set paths [find_timing_paths -from $all_registers_list -to $all_registers_list -sort_by_slack -group_path_count 5]
    } elseif {$group == "in2out"} {
        set all_inputs_list [all_inputs]
        set all_outputs_list [all_outputs]
        set paths [find_timing_paths -from $all_inputs_list -to $all_outputs_list -sort_by_slack -group_path_count 5]
    } else {
        set paths {}
    }
    if {[llength $paths] > 0} {
        set f [open ${output_base}/${target_name}_${group}_paths.rpt w]
        puts $f "# Timing paths for group: $group"
        if {[llength [all_clocks]] > 0} {
            puts $f "# Clock period: [get_property $clock period] ps"
        }
        puts $f ""
        foreach path $paths {
            set slack [get_property $path slack]
            set startpoint [get_property $path startpoint]
            set endpoint [get_property $path endpoint]
            puts $f "Path slack: $slack ps"
            puts $f "Startpoint: $startpoint"
            puts $f "Endpoint: $endpoint"
            puts $f "---"
        }
        close $f
    } else {
        # Create empty file if no paths found
        set f [open ${output_base}/${target_name}_${group}_paths.rpt w]
        puts $f "# No timing paths found for group: $group"
        close $f
    }
}

# Create the required output file (dummy)
set f [open $::env(OUTPUT) w]
puts $f "Timing reports generated successfully"
close $f
