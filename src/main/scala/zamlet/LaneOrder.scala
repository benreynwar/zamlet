package zamlet

import chisel3._

object LaneOrder extends ChiselEnum {
  val MOORE = Value(0.U)
  val UNKNOWN1 = Value(1.U)
  val ROW_MAJOR = Value(2.U)
  val TOROIDAL_ROW_MAJOR = Value(3.U)
  val COLUMN_MAJOR = Value(4.U)
  val TOROIDAL_COLUMN_MAJOR = Value(5.U)

  def count: Int = all.length
}

object LaneOrderMapping {
  private object MooreOrientation extends ChiselEnum {
    val N = Value(0.U)
    val E = Value(1.U)
    val S = Value(2.U)
    val W = Value(3.U)
  }

  private object MooreQuadrant extends ChiselEnum {
    val NE = Value(0.U)
    val SE = Value(1.U)
    val SW = Value(2.U)
    val NW = Value(3.U)
  }

  private class MooreNode extends Bundle {
    val orientation = MooreOrientation()
    val dir = Bool()
  }

  private def index(order: LaneOrder.Type): Int = order.asUInt.litValue.toInt

  private def qIntoOrientation(
    quadrant: MooreQuadrant.Type,
    orientation: MooreOrientation.Type
  ): MooreQuadrant.Type = {
    (quadrant.asUInt - orientation.asUInt).asTypeOf(quadrant)
  }

  private def oOutOfOrientation(
    original: MooreOrientation.Type,
    orientation: MooreOrientation.Type
  ): MooreOrientation.Type = {
    (original.asUInt + orientation.asUInt).asTypeOf(original)
  }

  private def xyToQuadrant(x: Bool, y: Bool): MooreQuadrant.Type = {
    val q = Wire(MooreQuadrant())
    when (!x && !y) {
      q := MooreQuadrant.NW
    } .elsewhen (!x && y) {
      q := MooreQuadrant.SW
    } .elsewhen (x && !y) {
      q := MooreQuadrant.NE
    } .otherwise {
      q := MooreQuadrant.SE
    }
    q
  }

  private def getSubNode(iNode: MooreNode, quadrant: MooreQuadrant.Type): MooreNode = {
    val oNode = Wire(new MooreNode)
    when (quadrant === MooreQuadrant.NW) {
      oNode.dir := !iNode.dir
      oNode.orientation := oOutOfOrientation(iNode.orientation, MooreOrientation.W)
    } .elsewhen (quadrant === MooreQuadrant.SW) {
      oNode.dir := iNode.dir
      oNode.orientation := iNode.orientation
    } .elsewhen (quadrant === MooreQuadrant.SE) {
      oNode.dir := iNode.dir
      oNode.orientation := iNode.orientation
    } .otherwise {
      oNode.dir := !iNode.dir
      oNode.orientation := oOutOfOrientation(iNode.orientation, MooreOrientation.E)
    }
    oNode
  }

  private def getFirstNode(quadrant: MooreQuadrant.Type): MooreNode = {
    val oNode = Wire(new MooreNode)
    oNode.dir := false.B
    when (quadrant === MooreQuadrant.SE) {
      oNode.orientation := MooreOrientation.W
    } .elsewhen (quadrant === MooreQuadrant.NE) {
      oNode.orientation := MooreOrientation.W
    } .otherwise {
      oNode.orientation := MooreOrientation.E
    }
    oNode
  }

  def rowMajor(params: ZamletParams, x: UInt, y: UInt): UInt = {
    (y * params.jTotalCols.U + x)(params.log2JInL - 1, 0)
  }

  def columnMajor(params: ZamletParams, x: UInt, y: UInt): UInt = {
    (x * params.jTotalRows.U + y)(params.log2JInL - 1, 0)
  }

  def toroidalRowMajor(params: ZamletParams, x: UInt, y: UInt): UInt = {
    require(params.jTotalRows >= 2, "Toroidal row-major lane order requires at least two rows")
    val rowPair = y >> 1
    val rowRank = Mux(y(0), (params.jTotalRows - 1).U - rowPair, rowPair)
    val orderedX = Mux(rowRank(0), (params.jTotalCols - 1).U - x, x)
    (rowRank * params.jTotalCols.U + orderedX)(params.log2JInL - 1, 0)
  }

  def toroidalColumnMajor(params: ZamletParams, x: UInt, y: UInt): UInt = {
    require(params.jTotalCols >= 2, "Toroidal column-major lane order requires at least two columns")
    val columnPair = x >> 1
    val columnRank = Mux(x(0), (params.jTotalCols - 1).U - columnPair, columnPair)
    val orderedY = Mux(columnRank(0), (params.jTotalRows - 1).U - y, y)
    (columnRank * params.jTotalRows.U + orderedY)(params.log2JInL - 1, 0)
  }

  def moore(params: ZamletParams, x: UInt, y: UInt): UInt = {
    require(params.jTotalCols == params.jTotalRows,
      s"Moore lane order requires a square jamlet grid, got ${params.jTotalCols}x${params.jTotalRows}")
    require(params.xPosWidth == params.yPosWidth)

    val nLayers = params.log2JTotal / 2
    val outputNodes = Seq.fill(nLayers - 1)(Wire(new MooreNode))
    val outputIndices = Seq.fill(nLayers)(Wire(UInt((params.xPosWidth + params.yPosWidth).W)))
    val x0 = x(params.log2JTotalCols - 1)
    val y0 = y(params.log2JTotalRows - 1)
    val quadrant = xyToQuadrant(x0, y0)
    outputIndices(0) := quadrant.asUInt
    if (nLayers > 1) {
      outputNodes(0) := getFirstNode(quadrant)
    }

    for (layerIndex <- 1 until nLayers) {
      val xi = x(params.log2JTotalCols - layerIndex - 1)
      val yi = y(params.log2JTotalRows - layerIndex - 1)
      val quadrant = xyToQuadrant(xi, yi)
      val lastNode = outputNodes(layerIndex - 1)
      val rotatedQuadrant = qIntoOrientation(quadrant, lastNode.orientation)
      val index = Wire(UInt(2.W))
      when (lastNode.dir) {
        index := 3.U - rotatedQuadrant.asUInt
      } .otherwise {
        index := rotatedQuadrant.asUInt
      }
      outputIndices(layerIndex) := (outputIndices(layerIndex - 1) << 2) + index
      if (layerIndex < nLayers - 1) {
        outputNodes(layerIndex) := getSubNode(lastNode, rotatedQuadrant)
      }
    }
    outputIndices(nLayers - 1)(params.log2JInL - 1, 0)
  }

  def indices(params: ZamletParams, x: UInt, y: UInt): Vec[UInt] = {
    val result = Wire(Vec(LaneOrder.count, UInt(params.log2JInL.W)))
    for (i <- 0 until LaneOrder.count) {
      result(i) := 0.U
    }
    result(index(LaneOrder.MOORE)) := moore(params, x, y)
    result(index(LaneOrder.ROW_MAJOR)) := rowMajor(params, x, y)
    result(index(LaneOrder.TOROIDAL_ROW_MAJOR)) := toroidalRowMajor(params, x, y)
    result(index(LaneOrder.COLUMN_MAJOR)) := columnMajor(params, x, y)
    result(index(LaneOrder.TOROIDAL_COLUMN_MAJOR)) := toroidalColumnMajor(params, x, y)
    result
  }
}
