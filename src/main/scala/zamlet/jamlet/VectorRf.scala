package zamlet.jamlet

import chisel3._
import chisel3.util._
import io.circe.generic.semiauto._
import io.circe._
import io.circe.parser._
import zamlet.utils.DoubleBuffer

case class VectorRfParams(
  nWords: Int = 48,
  wordWidth: Int = 64,
  nReadPorts: Int = 3,
  nWritePorts: Int = 1
) {
  val addrWidth: Int = log2Ceil(nWords)
}

object VectorRfParams {
  implicit val decoder: Decoder[VectorRfParams] =
    deriveDecoder[VectorRfParams]

  def fromFile(fileName: String): VectorRfParams = {
    val jsonContent = scala.io.Source.fromFile(fileName).mkString
    decode[VectorRfParams](jsonContent) match {
      case Right(params) => params
      case Left(error) =>
        throw new RuntimeException(
          s"Failed to parse VectorRfParams from $fileName: $error")
    }
  }
}

/**
 * Vector register file slice with configurable read and write port counts.
 * All ports are double-buffered (forward and backward).
 *
 * Read ports are combinational (between the buffers).
 * Write ports are registered. Two writes to the same address is DontCare.
 */
class VectorRf(params: VectorRfParams) extends Module {
  val io = IO(new Bundle {
    val readPorts = Vec(params.nReadPorts, new Bundle {
      val req = Flipped(Decoupled(new Bundle {
        val addr = UInt(params.addrWidth.W)
      }))
      val resp = Decoupled(new Bundle {
        val data = UInt(params.wordWidth.W)
      })
    })
    val writePorts = Vec(params.nWritePorts, new Bundle {
      val req = Flipped(Decoupled(new Bundle {
        val addr = UInt(params.addrWidth.W)
        val data = UInt(params.wordWidth.W)
      }))
    })
  })

  val mem = Reg(Vec(params.nWords, UInt(params.wordWidth.W)))

  // Read ports: combinational read between double buffers
  for (i <- 0 until params.nReadPorts) {
    val req = DoubleBuffer(io.readPorts(i).req, true, true)
    val resp = Wire(Decoupled(io.readPorts(i).resp.bits.cloneType))
    io.readPorts(i).resp <> DoubleBuffer(resp, true, true)

    req.ready := resp.ready
    resp.valid := req.valid
    resp.bits.data := mem(req.bits.addr)
  }

  // Write ports: always ready (between double buffers)
  for (i <- 0 until params.nWritePorts) {
    val req = DoubleBuffer(io.writePorts(i).req, true, true)
    req.ready := true.B

    when(req.fire) {
      mem(req.bits.addr) := req.bits.data
    }
  }
}

object VectorRfGenerator extends zamlet.ModuleGenerator {
  override def makeModule(args: Seq[String]): chisel3.Module = {
    val params = VectorRfParams.fromFile(args(0))
    new VectorRf(params)
  }
}

object VectorRfMain extends App {
  if (args.length < 2) {
    println("Usage: <outputDir> <configFile>")
    System.exit(1)
  }
  VectorRfGenerator.generate(args(0), Seq(args(1)))
}
