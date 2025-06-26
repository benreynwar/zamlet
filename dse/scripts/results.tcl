# Area and timing extraction script for FMVPU NetworkNode DSE
# Adapted from RegFileStudy: https://github.com/Pinata-Consulting/RegFileStudy

source $::env(SCRIPTS_DIR)/open.tcl

set clock [lindex [all_clocks] 0]
set clock_period [get_property $clock period]

set f [open $::env(OUTPUT) a]
puts $f "name: $::env(DESIGN_NAME)"
foreach group {in2reg reg2out} {
  set paths [find_timing_paths -path_group $group -sort_by_slack -group_path_count 1]
  set path [lindex $paths 0]
  set slack [get_property $path slack]
  puts $f "${group}_arrival: [expr $clock_period - $slack]"
}
puts $f "instances: [llength [get_cells *]]"
puts $f "area: [sta::format_area [rsz::design_area] 0]"

set_power_activity -input -activity 0.5

report_power > tmp.txt
exec cat tmp.txt
set f2 [open tmp.txt r]
set power_line [lindex [split [read $f2] "\n"] 9]
regexp {(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)} $power_line -> _ _ _ _ power
close $f2

report_clock_min_period
set clock_period_ps [sta::find_clk_min_period $clock 0]

puts $f "power: $power"
puts $f "clock_period: $clock_period"
puts $f "min_clock_period: $clock_period_ps"
close $f