# LocalExec RF request outputs feed nearby RF-slice logic in the Jamlet.
# Keep the default macro output delay for other outputs, but reserve less of the
# cycle for these local request ports.
set localexec_rf_req_outputs [get_ports {
    io_rfReadAReq_*
    io_rfReadBReq_*
    io_rfReadMaskReq_*
    io_rfWriteReq_*
}]

set localexec_rf_req_output_delay_pct 20
set localexec_rf_req_output_delay_value [expr $::env(CLOCK_PERIOD) * $localexec_rf_req_output_delay_pct / 100]
puts "\[INFO] Setting LocalExec RF request output delay to: $localexec_rf_req_output_delay_value"
set_output_delay $localexec_rf_req_output_delay_value -clock $clocks $localexec_rf_req_outputs
