module cvc_smoke (
    input wire clock,
    input wire reset,
    input wire [7:0] data_in,
    output reg [7:0] data_out
);
  always @(posedge clock) begin
    if (reset)
      data_out <= 8'h00;
    else
      data_out <= data_in;
  end
endmodule
