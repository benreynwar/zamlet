package zamlet.maths

import chisel3._
import chisel3.util._
import zamlet.ModuleGenerator
import io.circe._
import io.circe.parser._
import io.circe.generic.semiauto._
import scala.io.Source

case class CarrySelectAdderParams(
  width: Int,
  sectionWidth: Int,
  regAfterSectionCalc: Boolean = false,
  regAfterCarryCalc: Boolean = false
) {
  val numSections: Int = (width + sectionWidth - 1) / sectionWidth
  val paddedWidth: Int = numSections * sectionWidth
}

class CarrySelectAdder(params: CarrySelectAdderParams) extends Module {
  import params._

  override def desiredName = {
    val regStr = (regAfterSectionCalc, regAfterCarryCalc) match {
      case (true, true) => "_Reg2"
      case (true, false) => "_RegSec"
      case (false, true) => "_RegCarry"
      case (false, false) => ""
    }
    s"CarrySelectAdder${width}_${sectionWidth}${regStr}"
  }

  val io = IO(new Bundle {
    val a = Input(UInt(width.W))
    val b = Input(UInt(width.W))
    val sum = Output(UInt((width + 1).W))
  })

  // Pad inputs to multiple of sectionWidth
  val aPadded = if (paddedWidth > width) Cat(0.U((paddedWidth - width).W), io.a) else io.a
  val bPadded = if (paddedWidth > width) Cat(0.U((paddedWidth - width).W), io.b) else io.b

  // Stage 1: Compute all sections in parallel
  // Each section computes sum0 (cin=0) and sum1 (cin=1) speculatively
  val sum0Results = Wire(Vec(numSections, UInt(sectionWidth.W)))
  val sum0Carries = Wire(Vec(numSections, Bool()))
  val sum1Results = Wire(Vec(numSections, UInt(sectionWidth.W)))
  val sum1Carries = Wire(Vec(numSections, Bool()))

  for (i <- 0 until numSections) {
    val lo = i * sectionWidth
    val hi = (i + 1) * sectionWidth

    val aSec = aPadded(hi - 1, lo)
    val bSec = bPadded(hi - 1, lo)

    val sum0 = aSec +& bSec
    val sum1 = aSec +& bSec +& 1.U

    sum0Results(i) := sum0(sectionWidth - 1, 0)
    sum0Carries(i) := sum0(sectionWidth)
    sum1Results(i) := sum1(sectionWidth - 1, 0)
    sum1Carries(i) := sum1(sectionWidth)
  }

  // Optionally register after section calculation (before carry prefix tree)
  val results0 = if (regAfterSectionCalc) RegNext(sum0Results) else sum0Results
  val carries0 = if (regAfterSectionCalc) RegNext(sum0Carries) else sum0Carries
  val results1 = if (regAfterSectionCalc) RegNext(sum1Results) else sum1Results
  val carries1 = if (regAfterSectionCalc) RegNext(sum1Carries) else sum1Carries

  // Stage 2: Compute carries using parallel prefix tree (Kogge-Stone style - at least LLM thought so)
  // G (generate) = carries0[i] -- produces carry even with cin=0
  // P (propagate) = carries1[i] && !carries0[i] -- passes cin to cout
  val generates = Wire(Vec(numSections, Bool()))
  val propagates = Wire(Vec(numSections, Bool()))

  for (i <- 0 until numSections) {
    generates(i) := carries0(i)
    propagates(i) := carries1(i) && !carries0(i)
  }

  // Parallel prefix tree to compute carry into each section
  // Using prefix computation: (G, P) combines as G' = G1 | (P1 & G0), P' = P1 & P0
  val numLevels = log2Ceil(numSections)

  // Create all levels upfront with proper names
  val prefixG = Seq.tabulate(numLevels + 1)(level => Wire(Vec(numSections, Bool())).suggestName(s"prefixG_$level"))
  val prefixP = Seq.tabulate(numLevels + 1)(level => Wire(Vec(numSections, Bool())).suggestName(s"prefixP_$level"))

  // Level 0 is the initial G/P values
  for (i <- 0 until numSections) {
    prefixG(0)(i) := generates(i)
    prefixP(0)(i) := propagates(i)
  }

  // Build prefix tree - each level combines pairs with increasing stride
  for (level <- 0 until numLevels) {
    val stride = 1 << level
    for (i <- 0 until numSections) {
      if (i >= stride) {
        prefixG(level + 1)(i) := prefixG(level)(i) || (prefixP(level)(i) && prefixG(level)(i - stride))
        prefixP(level + 1)(i) := prefixP(level)(i) && prefixP(level)(i - stride)
      } else {
        prefixG(level + 1)(i) := prefixG(level)(i)
        prefixP(level + 1)(i) := prefixP(level)(i)
      }
    }
  }

  // After prefix tree, prefixG(numLevels)(i) = carry out of section i
  // carryIn to section i is prefixG(numLevels)(i-1) for i > 0, and false for i = 0
  val carryInComb = Wire(Vec(numSections, Bool()))
  carryInComb(0) := false.B
  for (i <- 1 until numSections) {
    carryInComb(i) := prefixG(numLevels)(i - 1)
  }

  // Optionally register after carry calculation (before final mux)
  val carryInToUse = if (regAfterCarryCalc) RegNext(carryInComb) else carryInComb
  val results0ToMux = if (regAfterCarryCalc) RegNext(results0) else results0
  val results1ToMux = if (regAfterCarryCalc) RegNext(results1) else results1

  // Select results based on computed carries
  val resultBits = Wire(Vec(numSections, UInt(sectionWidth.W)))
  for (i <- 0 until numSections) {
    resultBits(i) := Mux(carryInToUse(i), results1ToMux(i), results0ToMux(i))
  }

  // Final carry out
  val carryOut = prefixG(numLevels)(numSections - 1)

  val fullResult = Cat(carryOut, resultBits.asUInt)
  io.sum := fullResult(width, 0)
}

object CarrySelectAdderParams {
  implicit val decoder: Decoder[CarrySelectAdderParams] = deriveDecoder[CarrySelectAdderParams]

  def fromFile(fileName: String): CarrySelectAdderParams = {
    val jsonContent: String = Source.fromFile(fileName).mkString
    decode[CarrySelectAdderParams](jsonContent) match {
      case Right(params) => params
      case Left(error) =>
        println(s"Failed to parse JSON: ${error}")
        System.exit(1)
        null
    }
  }
}

object CarrySelectAdderGenerator extends ModuleGenerator {
  override def makeModule(args: Seq[String]): Module = {
    if (args.isEmpty) {
      println("Usage: <outputDir> <configFile>")
      null
    } else {
      new CarrySelectAdder(CarrySelectAdderParams.fromFile(args(0)))
    }
  }
}

object CarrySelectAdderMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  CarrySelectAdderGenerator.generate(args(0), Seq(args(1)))
}
