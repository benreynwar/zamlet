package zamlet.jamlet

import chisel3._
import chisel3.util._
import zamlet.{LaneOrder, ZamletParams}

class LaneIndexToCoordsIO(params: ZamletParams) extends Bundle {
  val laneIndex = Input(UInt(params.log2JInL.W))
  val laneOrder = Input(LaneOrder())
  val x = Output(UInt(params.xPosWidth.W))
  val y = Output(UInt(params.yPosWidth.W))
}

class LaneIndexToCoords(params: ZamletParams) extends Module {
  val io = IO(new LaneIndexToCoordsIO(params))

  val moore = Module(new IndexToCoords(params))
  moore.io.index := io.laneIndex

  val rowMajorX = io.laneIndex % params.jTotalCols.U
  val rowMajorY = io.laneIndex / params.jTotalCols.U
  val columnMajorX = io.laneIndex / params.jTotalRows.U
  val columnMajorY = io.laneIndex % params.jTotalRows.U

  val toroidalRowRank = io.laneIndex / params.jTotalCols.U
  val toroidalRowOrderedX = io.laneIndex % params.jTotalCols.U
  val toroidalRowEvenCount = ((params.jTotalRows + 1) / 2).U
  val toroidalRowPair = Mux(
    toroidalRowRank < toroidalRowEvenCount,
    toroidalRowRank,
    (params.jTotalRows - 1).U - toroidalRowRank
  )
  val toroidalRowX = Mux(
    toroidalRowRank(0),
    (params.jTotalCols - 1).U - toroidalRowOrderedX,
    toroidalRowOrderedX
  )
  val toroidalRowY = Mux(
    toroidalRowRank < toroidalRowEvenCount,
    toroidalRowPair << 1,
    (toroidalRowPair << 1) + 1.U
  )

  val toroidalColumnRank = io.laneIndex / params.jTotalRows.U
  val toroidalColumnOrderedY = io.laneIndex % params.jTotalRows.U
  val toroidalColumnEvenCount = ((params.jTotalCols + 1) / 2).U
  val toroidalColumnPair = Mux(
    toroidalColumnRank < toroidalColumnEvenCount,
    toroidalColumnRank,
    (params.jTotalCols - 1).U - toroidalColumnRank
  )
  val toroidalColumnX = Mux(
    toroidalColumnRank < toroidalColumnEvenCount,
    toroidalColumnPair << 1,
    (toroidalColumnPair << 1) + 1.U
  )
  val toroidalColumnY = Mux(
    toroidalColumnRank(0),
    (params.jTotalRows - 1).U - toroidalColumnOrderedY,
    toroidalColumnOrderedY
  )

  io.x := 0.U
  io.y := 0.U
  when (io.laneOrder === LaneOrder.MOORE) {
    io.x := moore.io.x
    io.y := moore.io.y
  } .elsewhen (io.laneOrder === LaneOrder.ROW_MAJOR) {
    io.x := rowMajorX
    io.y := rowMajorY
  } .elsewhen (io.laneOrder === LaneOrder.TOROIDAL_ROW_MAJOR) {
    io.x := toroidalRowX
    io.y := toroidalRowY
  } .elsewhen (io.laneOrder === LaneOrder.COLUMN_MAJOR) {
    io.x := columnMajorX
    io.y := columnMajorY
  } .elsewhen (io.laneOrder === LaneOrder.TOROIDAL_COLUMN_MAJOR) {
    io.x := toroidalColumnX
    io.y := toroidalColumnY
  }
}
