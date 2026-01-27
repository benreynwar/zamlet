package zamlet.maths

import chisel3._
import chisel3.util._
import zamlet.ModuleGenerator
import io.circe._
import io.circe.parser._
import io.circe.generic.semiauto._
import scala.io.Source

case class WallaceMultParams(
  xBits: Int,
  yBits: Int,
  registerInput: Boolean = false,
  registerOutput: Boolean = false,
  regEveryNStages: Option[Int] = None,
  regBeforeFinalAdd: Boolean = false,
  finalAdderSectionWidth: Option[Int] = None,
  finalAdderRegAfterSectionCalc: Boolean = false,
  finalAdderRegAfterCarryCalc: Boolean = false,
  inputRegFanoutLimit: Option[Int] = None
) {
  val resultWidth: Int = xBits + yBits
}

class WallaceMult(params: WallaceMultParams) extends Module {
  import params._

  override def desiredName = s"WallaceMult${xBits}x${yBits}"

  val io = IO(new Bundle {
    val x = Input(UInt(xBits.W))
    val y = Input(UInt(yBits.W))
    val out = Output(UInt(resultWidth.W))
  })

  // Optionally register inputs with duplication to reduce fanout
  val numRegCopies: Int = inputRegFanoutLimit match {
    case Some(limit) if registerInput && limit > 0 => (yBits + limit - 1) / limit
    case _ => 1
  }

  val xRegs: Seq[UInt] = if (registerInput) {
    Seq.fill(numRegCopies)(RegNext(io.x))
  } else {
    Seq(io.x)
  }

  val yRegs: Seq[UInt] = if (registerInput) {
    Seq.fill(numRegCopies)(RegNext(io.y))
  } else {
    Seq(io.y)
  }

  // Generate partial products
  // For each bit y[j], partial product is: Mux(y(j), x << j, 0)
  // Use register copy based on fanout limit
  val partialProducts: Seq[UInt] = (0 until yBits).map { j =>
    val regIdx = inputRegFanoutLimit match {
      case Some(limit) if limit > 0 => j / limit
      case _ => 0
    }
    val xToUse = xRegs(regIdx min (numRegCopies - 1))
    val yToUse = yRegs(regIdx min (numRegCopies - 1))
    Mux(yToUse(j), xToUse << j, 0.U(resultWidth.W))
  }

  // Build WallaceTreeAdder params matching our pipeline config
  val adderParams = WallaceTreeAdderParams(
    inputWidth = resultWidth,
    numInputs = yBits,
    registerInput = false,
    registerOutput = false,
    regEveryNStages = regEveryNStages,
    regBeforeFinalAdd = regBeforeFinalAdd,
    finalAdderSectionWidth = finalAdderSectionWidth,
    finalAdderRegAfterSectionCalc = finalAdderRegAfterSectionCalc,
    finalAdderRegAfterCarryCalc = finalAdderRegAfterCarryCalc
  )

  val adder = Module(new ConfigurableWallaceTreeAdder(adderParams))
  for (j <- 0 until yBits) {
    adder.io.inputs(j) := partialProducts(j)
  }

  // Optionally register output
  val result: UInt = adder.io.sum(resultWidth - 1, 0)
  io.out := (if (registerOutput) RegNext(result) else result)
}

object WallaceMultParams {
  implicit val decoder: Decoder[WallaceMultParams] = deriveDecoder[WallaceMultParams]

  def fromFile(fileName: String): WallaceMultParams = {
    val jsonContent: String = Source.fromFile(fileName).mkString
    decode[WallaceMultParams](jsonContent) match {
      case Right(params) => params
      case Left(error) =>
        println(s"Failed to parse JSON: ${error}")
        System.exit(1)
        null
    }
  }
}

object WallaceMultGenerator extends ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.isEmpty) {
      println("Usage: <outputDir> <configFile>")
      null
    } else {
      new WallaceMult(WallaceMultParams.fromFile(args(0)))
    }
  }
}

object WallaceMultMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  WallaceMultGenerator.generate(args(0), Seq(args(1)))
}
