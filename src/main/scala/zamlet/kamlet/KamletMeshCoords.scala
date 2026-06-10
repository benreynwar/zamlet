package zamlet.kamlet

import chisel3._
import zamlet.ZamletParams

object KamletMeshCoords {
  def halfCols(params: ZamletParams): Int = params.kCols / 2

  def sideJnetCols(params: ZamletParams): Int = {
    (halfCols(params) + params.jRows - 1) / params.jRows
  }

  def coordsPerMemlet(params: ZamletParams): Int = {
    if (halfCols(params) <= params.jRows) {
      params.jRows / halfCols(params)
    } else {
      1
    }
  }

  def kamletKnetXInt(params: ZamletParams, knetOffsetX: Int, kX: Int): Int = {
    knetOffsetX + kX
  }

  def kamletKnetYInt(params: ZamletParams, knetOffsetY: Int, kY: Int): Int = {
    knetOffsetY + kY
  }

  def memletKnetXInt(params: ZamletParams, knetOffsetX: Int, kX: Int): Int = {
    if (kX < halfCols(params)) {
      knetOffsetX + kX - halfCols(params)
    } else {
      knetOffsetX + kX + halfCols(params)
    }
  }

  def memletKnetYInt(params: ZamletParams, knetOffsetY: Int, kY: Int): Int = {
    kamletKnetYInt(params, knetOffsetY, kY)
  }

  def kamletJnetBaseXInt(params: ZamletParams, kX: Int): Int = {
    sideJnetCols(params) + kX * params.jCols
  }

  def kamletJnetBaseYInt(params: ZamletParams, kY: Int): Int = {
    kY * params.jRows
  }

  def memletJnetRouterXInt(params: ZamletParams, kX: Int, router: Int): Int = {
    val kXInHalf =
      if (kX < halfCols(params)) kX else params.kCols - 1 - kX
    val sideSlot = kXInHalf * coordsPerMemlet(params) + router
    val memletCol = sideSlot / params.jRows
    if (kX < halfCols(params)) {
      memletCol
    } else {
      sideJnetCols(params) + params.kCols * params.jCols +
        (sideJnetCols(params) - 1 - memletCol)
    }
  }

  def memletJnetRouterYInt(params: ZamletParams, kX: Int, kY: Int, router: Int): Int = {
    val kXInHalf =
      if (kX < halfCols(params)) kX else params.kCols - 1 - kX
    val sideSlot = kXInHalf * coordsPerMemlet(params) + router
    val memletRow = sideSlot % params.jRows
    kY * params.jRows + memletRow
  }

  def kamletKnetX(params: ZamletParams, knetOffsetX: UInt, kX: Int): UInt = {
    knetOffsetX + kX.U(params.xPosWidth.W)
  }

  def kamletKnetY(params: ZamletParams, knetOffsetY: UInt, kY: Int): UInt = {
    knetOffsetY + kY.U(params.yPosWidth.W)
  }

  def memletKnetX(params: ZamletParams, knetOffsetX: UInt, kX: Int): UInt = {
    val kXOffset = kX.U(params.xPosWidth.W)
    val half = halfCols(params).U(params.xPosWidth.W)
    if (kX < halfCols(params)) {
      knetOffsetX + kXOffset - half
    } else {
      knetOffsetX + kXOffset + half
    }
  }

  def memletKnetY(params: ZamletParams, knetOffsetY: UInt, kY: Int): UInt = {
    kamletKnetY(params, knetOffsetY, kY)
  }

  def kamletJnetBaseX(params: ZamletParams, kX: Int): UInt = {
    kamletJnetBaseXInt(params, kX).U(params.xPosWidth.W)
  }

  def kamletJnetBaseY(params: ZamletParams, kY: Int): UInt = {
    kamletJnetBaseYInt(params, kY).U(params.yPosWidth.W)
  }

  def memletJnetX(params: ZamletParams, kX: Int, jInK: Int): UInt = {
    val router = (jInK / params.jCols) % coordsPerMemlet(params)
    memletJnetRouterX(params, kX, router)
  }

  def memletJnetY(params: ZamletParams, kX: Int, kY: Int, jInK: Int): UInt = {
    val router = (jInK / params.jCols) % coordsPerMemlet(params)
    memletJnetRouterY(params, kX, kY, router)
  }

  def memletJnetRouterX(params: ZamletParams, kX: Int, router: Int): UInt = {
    memletJnetRouterXInt(params, kX, router).U(params.xPosWidth.W)
  }

  def memletJnetRouterY(params: ZamletParams, kX: Int, kY: Int, router: Int): UInt = {
    memletJnetRouterYInt(params, kX, kY, router).U(params.yPosWidth.W)
  }
}
