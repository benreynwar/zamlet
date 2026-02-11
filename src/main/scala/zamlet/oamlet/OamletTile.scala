package zamlet.oamlet

import chisel3._
import chisel3.util._

import org.chipsalliance.cde.config._
import freechips.rocketchip.subsystem._
import freechips.rocketchip.diplomacy._
import freechips.rocketchip.tilelink._
import freechips.rocketchip.tile._
import freechips.rocketchip.rocket.{BTBParams, DCacheParams, ICacheParams}
import freechips.rocketchip.trace.TraceEncoderParams
import freechips.rocketchip.prci.ClockSinkParameters
import shuttle.common._
import shuttle.dmem.{ShuttleSGTCMParams, ShuttleDCacheParams}
import zamlet.lamlet.Zamlet

case object VPUMemParamsKey extends Field[VPUMemParams]

case class VPUMemParams(
  base: BigInt,
  size: BigInt) extends TCMParams

case class OamletTileParams(
  core: ShuttleCoreParams = ShuttleCoreParams(),
  icache: Option[ICacheParams] = Some(ICacheParams(prefetch = true)),
  dcacheParams: ShuttleDCacheParams = ShuttleDCacheParams(),
  trace: Boolean = false,
  name: Option[String] = Some("shuttle_tile"),
  btb: Option[BTBParams] = Some(BTBParams()),
  tcm: Option[ShuttleTCMParams] = None,
  sgtcm: Option[ShuttleSGTCMParams] = None,
  tileId: Int = 0,
  tileBeatBytes: Int = 8,
  boundaryBuffers: Boolean = false,
  traceParams: Option[TraceEncoderParams] = None
) extends InstantiableTileParams[OamletTile] {
  require(icache.isDefined)
  def instantiate(
    crossing: HierarchicalElementCrossingParamsLike,
    lookup: LookupByHartIdImpl
  )(implicit p: Parameters): OamletTile = {
    new OamletTile(this, crossing, lookup)
  }

  def toShuttleTileParams = ShuttleTileParams(
    core = core,
    icache = icache,
    dcacheParams = dcacheParams,
    trace = trace,
    name = name,
    btb = btb,
    tcm = tcm,
    sgtcm = sgtcm,
    tileId = tileId,
    tileBeatBytes = tileBeatBytes,
    boundaryBuffers = boundaryBuffers,
    traceParams = traceParams
  )

  val beuAddr: Option[BigInt] = None
  val blockerCtrlAddr: Option[BigInt] = None
  val dcache = Some(DCacheParams(
    rowBits = 64,
    nSets = dcacheParams.nSets,
    nWays = dcacheParams.nWays,
    nMSHRs = dcacheParams.nMSHRs,
    nMMIOs = dcacheParams.nMMIOs
  ))
  val clockSinkParams: ClockSinkParameters = ClockSinkParameters()
  val baseName = name.getOrElse("shuttle_tile")
  val uniqueName = s"${baseName}_$tileId"
}

case class OamletTileAttachParams(
  tileParams: OamletTileParams,
  crossingParams: ShuttleCrossingParams
) extends CanAttachTile {
  type TileType = OamletTile
  val lookup = PriorityMuxHartIdFromSeq(Seq(tileParams))
}

class OamletTile(
  val oamletParams: OamletTileParams,
  crossing: HierarchicalElementCrossingParamsLike,
  lookup: LookupByHartIdImpl
)(implicit p: Parameters) extends ShuttleTile(
  oamletParams.toShuttleTileParams,
  crossing,
  lookup
) {
  val vpuMemParams = p(VPUMemParamsKey)

  val zamlet = vector_unit.get.asInstanceOf[Zamlet]

  DisableMonitors { implicit p =>
    zamlet.vpuTLNode := TLBuffer() := tlSlaveXbar.node
  }

  override lazy val module = new OamletTileModuleImp(this)
}

class OamletTileModuleImp(outer: OamletTile)
  extends ShuttleTileModuleImp(outer)
