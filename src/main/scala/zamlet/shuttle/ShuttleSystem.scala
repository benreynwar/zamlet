package zamlet.shuttle

import chisel3._

import org.chipsalliance.cde.config._

import freechips.rocketchip.subsystem._
import freechips.rocketchip.devices.debug.HasPeripheryDebug
import freechips.rocketchip.devices.tilelink.{CanHavePeripheryCLINT, CanHavePeripheryPLIC}
import freechips.rocketchip.util.DontTouch

import shuttle.common._

/** Trait for accessing Shuttle tiles in a subsystem */
trait HasShuttleTiles {
  this: BaseSubsystem with InstantiatesHierarchicalElements =>
  val shuttleTiles = totalTiles.values.collect { case t: ShuttleTile => t }
}

/** Minimal Shuttle subsystem - a Shuttle tile with bus infrastructure */
class ShuttleSubsystem(implicit p: Parameters) extends BaseSubsystem
    with InstantiatesHierarchicalElements
    with HasTileNotificationSinks
    with HasTileInputConstants
    with CanHavePeripheryCLINT
    with CanHavePeripheryPLIC
    with HasPeripheryDebug
    with HasHierarchicalElementsRootContext
    with HasHierarchicalElements
    with HasShuttleTiles
{
  override lazy val module = new ShuttleSubsystemModuleImp(this)
}

class ShuttleSubsystemModuleImp[+L <: ShuttleSubsystem](_outer: L)
    extends BaseSubsystemModuleImp(_outer)
    with HasHierarchicalElementsRootContextModuleImp {
  override lazy val outer = _outer
}

/** Complete Shuttle system with memory and MMIO ports */
class ShuttleSystem(implicit p: Parameters) extends ShuttleSubsystem
    with HasAsyncExtInterrupts
    with CanHaveMasterAXI4MemPort
    with CanHaveMasterAXI4MMIOPort
{
  override lazy val module = new ShuttleSystemModuleImp(this)
}

class ShuttleSystemModuleImp[+L <: ShuttleSystem](_outer: L)
    extends ShuttleSubsystemModuleImp(_outer)
    with HasRTCModuleImp
    with HasExtInterruptsModuleImp
    with DontTouch
