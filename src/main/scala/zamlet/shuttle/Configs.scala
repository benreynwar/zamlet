package zamlet.shuttle

import org.chipsalliance.cde.config._

import freechips.rocketchip.subsystem._
import freechips.rocketchip.devices.tilelink._
import freechips.rocketchip.rocket.{BTBParams, BHTParams, ICacheParams}

import shuttle.common._

/** Scalar DRAM memory port config - 256GB starting at 0x1000000000 */
class WithScalarMemPort extends Config((site, here, up) => {
  case ExtMem => Some(MemoryPortParams(MasterPortParams(
    base = 0x80000000L,
    size = 0x80000000L,
    beatBytes = site(MemoryBusKey).beatBytes,
    idBits = 4), 1))
})

/** Base config for Shuttle systems - provides memory ports, timebase, bus topology */
class ShuttleBaseConfig extends Config(
  new WithScalarMemPort ++
  new WithDefaultMMIOPort ++
  new WithTimebase(BigInt(1000000)) ++  // 1 MHz
  new WithDTS("zamlet,shuttle", Nil) ++
  new WithNExtTopInterrupts(0) ++
  new freechips.rocketchip.subsystem.WithoutTLMonitors ++  // Disable TL monitors for faster sim
  new Config((site, here, up) => {
    // Expose reset vector as external IO (cocotb will drive it)
    case HasTilesExternalResetVectorKey => true
  }) ++
  new BaseSubsystemConfig
)

/** Minimal Shuttle config - single core with coherent bus */
class MinimalShuttleConfig extends Config(
  new shuttle.common.WithNShuttleCores(
    n = 1,
    retireWidth = 2
  ) ++
  new WithCoherentBusTopology ++
  new ShuttleBaseConfig
)

/** Small Shuttle config - reduced cache sizes for faster simulation */
class SmallShuttleConfig extends Config(
  new shuttle.common.WithL1ICacheSets(32) ++
  new shuttle.common.WithL1ICacheWays(2) ++
  new shuttle.common.WithL1DCacheSets(32) ++
  new shuttle.common.WithL1DCacheWays(2) ++
  new MinimalShuttleConfig
)
