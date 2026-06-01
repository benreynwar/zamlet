package zamlet.jamlet 

import chisel3._
import chisel3.util._
import zamlet.ZamletParams
import zamlet.utils.DoubleBuffer


//          goes to   _    _ 
//   |_|              _|  |_ 
//                         
//                   |_|  |_|

object MooreOrientation extends ChiselEnum {
  val N = Value(0.U)
  val E = Value(1.U)
  val S = Value(2.U)
  val W = Value(3.U)
}

object MooreQuadrant extends ChiselEnum {
  val NE = Value(0.U)
  val SE = Value(1.U)
  val SW = Value(2.U)
  val NW = Value(3.U)
}


class MooreNode extends Bundle {
  val orientation = MooreOrientation()
  val dir = Bool()
}

class BoolCoords extends Bundle {
  val x = Bool()
  val y = Bool()
}

object Helpers {

  def qOutOfOrientation(quadrant: MooreQuadrant.Type, orientation: MooreOrientation.Type): MooreQuadrant.Type = {
    (quadrant.asUInt + orientation.asUInt).asTypeOf(quadrant)
  }

  def qIntoOrientation(quadrant: MooreQuadrant.Type, orientation: MooreOrientation.Type): MooreQuadrant.Type = {
    (quadrant.asUInt - orientation.asUInt).asTypeOf(quadrant)
  }

  def oOutOfOrientation(original: MooreOrientation.Type, orientation: MooreOrientation.Type): MooreOrientation.Type = {
    (original.asUInt + orientation.asUInt).asTypeOf(original)
  }

  def xyToQuadrant(x: Bool, y: Bool): MooreQuadrant.Type = {
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


  def QuadrantToXY(q: MooreQuadrant.Type): BoolCoords = {
    val xy = Wire(new BoolCoords)
    when (q === MooreQuadrant.NW) {
      xy.x := false.B
      xy.y := false.B
    } .elsewhen (q === MooreQuadrant.SW) {
      xy.x := false.B
      xy.y := true.B
    } .elsewhen (q === MooreQuadrant.SE) {
      xy.x := true.B
      xy.y := true.B
    }. otherwise {
      xy.x := true.B
      xy.y := false.B
    }
    xy
  }

  def indexToQuadrant(params: ZamletParams, index: UInt): MooreQuadrant.Type ={
    index(params.log2JTotal-2, params.log2JTotal-1).asTypeOf(MooreQuadrant())
  }

  def getSubNode(params: ZamletParams, iNode: MooreNode, quadrant: MooreQuadrant.Type): MooreNode= {
    val oNode = Wire(new MooreNode)
    //  _   _   goes to  __    __    c1w  b1e
    //   |_|              _|  |_     b0n  c0n
    //                   |      |
    //    a0n            |  __  |
    //                   |_|  |_|
    
    //  |  _    goes to  |_    __    a1w  b1e
    //  |_|               _|  |_     b0n  c0n
    //                   |      |
    //                   |  __  |
    //   b0n             |_|  |_|
    
    // _  |     goes to  __    _|    c1w  a1e
    //  |_|               _|  |_     b0n  c0n
    //                   |      |
    //                   |  __  |
    //   c0n             |_|  |_|
    when (quadrant === MooreQuadrant.NW) {
      oNode.dir := ! iNode.dir
      oNode.orientation := Helpers.oOutOfOrientation(iNode.orientation, MooreOrientation.W)
    } .elsewhen (quadrant === MooreQuadrant.SW) {
      oNode.dir := iNode.dir
      oNode.orientation := iNode.orientation
    } .elsewhen (quadrant === MooreQuadrant.SE) {
      oNode.dir := iNode.dir
      oNode.orientation := iNode.orientation
    } .otherwise {
      oNode.dir := ! iNode.dir
      oNode.orientation := Helpers.oOutOfOrientation(iNode.orientation, MooreOrientation.E)
    }
    oNode
  }

  def getFirstNode(params: ZamletParams, quadrant: MooreQuadrant.Type): MooreNode = {
    val oNode = Wire(new MooreNode)
    when (quadrant === MooreQuadrant.NW) {
      oNode.dir := false.B
      oNode.orientation := MooreOrientation.E
    } .elsewhen (quadrant === MooreQuadrant.SW) {
      oNode.dir := false.B
      oNode.orientation := MooreOrientation.E
    } .elsewhen (quadrant === MooreQuadrant.SE) {
      oNode.dir := false.B
      oNode.orientation := MooreOrientation.W
    } .otherwise {
      oNode.dir := false.B
      oNode.orientation := MooreOrientation.W
    }
    oNode
  }

}

class CoordsToIndexIo(params: ZamletParams) extends Bundle {
  val x = Input(UInt(params.xPosWidth.W))
  val y = Input(UInt(params.yPosWidth.W))
  val index = Output(UInt((params.xPosWidth + params.yPosWidth).W))
}

class CoordsToIndex(params: ZamletParams) extends Module {
  require(params.xPosWidth == params.yPosWidth)
  val io = IO(new CoordsToIndexIo(params))
  val n_layers = params.log2JTotal/2
  val outputNodes = Seq.fill(n_layers-1)(Wire(new MooreNode))
  val outputIndices = Seq.fill(n_layers)(Wire(UInt((params.xPosWidth+params.yPosWidth).W)))
  // Get the initial quadrannt
  val x0: Bool = io.x(params.log2JTotalCols-1)
  val y0: Bool = io.y(params.log2JTotalRows-1)
  val quadrant = Helpers.xyToQuadrant(x0, y0)
  // Do the first layer
  outputIndices(0) := quadrant.asUInt
  if (n_layers > 1) {
    outputNodes(0) := Helpers.getFirstNode(params, quadrant)
  }

  for (layer_index <- 1 until  n_layers) {
    val xi: Bool = io.x(params.log2JTotalCols-layer_index-1)
    val yi: Bool = io.y(params.log2JTotalRows-layer_index-1)
    val quadrant = Helpers.xyToQuadrant(xi, yi)
    // Rotate the quadrant into the node's frame
    val lastNode = outputNodes(layer_index -1)
    val rotatedQuadrant = Helpers.qIntoOrientation(quadrant, lastNode.orientation)
    val index = Wire(UInt(2.W))
    when (lastNode.dir) {
      index := 3.U - rotatedQuadrant.asUInt
    } .otherwise {
      index := rotatedQuadrant.asUInt
    }
    outputIndices(layer_index) := (outputIndices(layer_index-1) << 2) + index
    if (layer_index < n_layers-1) {
      outputNodes(layer_index) := Helpers.getSubNode(params, lastNode, rotatedQuadrant)
    }
  }
  io.index := outputIndices(n_layers-1)
}

class IndexToCoords(params: ZamletParams) extends Module {
  require(params.xPosWidth == params.yPosWidth)
  val io = IO(Flipped(new CoordsToIndexIo(params)))
  val n_layers = params.log2JTotal/2
  val outputNodes = Seq.fill(n_layers)(Wire(new MooreNode))
  private val outputCoords = Seq.fill(n_layers)(Wire(new params.JCoords))
  val quadrant = (3.U - io.index(params.log2JTotal-1, params.log2JTotal-2)).asTypeOf(MooreQuadrant())
  outputNodes(0) := Helpers.getFirstNode(params, quadrant)
  val coords = Helpers.QuadrantToXY(quadrant)
  outputCoords(0).x := coords.x.asUInt
  outputCoords(0).y := coords.y.asUInt
  for (layer_index <- 1 until n_layers) {
    val lastNode = outputNodes(layer_index -1)
    val rotatedQuadrant = Wire(MooreQuadrant())
    when (lastNode.dir) {
      rotatedQuadrant := (io.index(params.log2JTotal-1-layer_index*2, params.log2JTotal-2-layer_index*2)).asTypeOf(MooreQuadrant())
    } .otherwise {
      rotatedQuadrant := (3.U - io.index(params.log2JTotal-1-layer_index*2, params.log2JTotal-2-layer_index*2)).asTypeOf(MooreQuadrant())
    }
    outputNodes(layer_index) := Helpers.getSubNode(params, lastNode, rotatedQuadrant)
    val quadrant = Helpers.qOutOfOrientation(rotatedQuadrant, lastNode.orientation)
    val coords = Helpers.QuadrantToXY(quadrant)
    outputCoords(layer_index).x := outputCoords(layer_index-1).x * 2.U + coords.x.asUInt
    outputCoords(layer_index).y := outputCoords(layer_index-1).y * 2.U + coords.y.asUInt
  }
  io.x := outputCoords(n_layers-1).x
  io.y := outputCoords(n_layers-1).y
}

class CoordsToIndexWithReg(params: ZamletParams) extends Module {
  val io = IO(new CoordsToIndexIo(params))
  val regx = RegNext(io.x)
  val regy = RegNext(io.y)
  val inner = Module(new CoordsToIndex(params))
  inner.io.x := regx
  inner.io.y := regy
  io.index := RegNext(inner.io.index)
}

class IndexToCoordsWithReg(params: ZamletParams) extends Module {
  val io = IO(Flipped(new CoordsToIndexIo(params)))
  val regindex = RegNext(io.index)
  val inner = Module(new IndexToCoords(params))
  inner.io.index := regindex
  io.x := RegNext(inner.io.x)
  io.y := RegNext(inner.io.y)
}

object CoordsToIndexWithRegGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    val params = ZamletParams.fromFile(args(0))
    new CoordsToIndexWithReg(params)
  }
}

object IndexToCoordsWithRegGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    val params = ZamletParams.fromFile(args(0))
    new IndexToCoordsWithReg(params)
  }
}

object CoordsToIndexWithRegMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  CoordsToIndexWithRegGenerator.generate(args(0), Seq(args(1)))
}

object IndexToCoordsWithRegMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  IndexToCoordsWithRegGenerator.generate(args(0), Seq(args(1)))
}
