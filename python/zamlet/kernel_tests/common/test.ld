/*======================================================================*/
/* Proxy kernel linker script                                           */
/*======================================================================*/
/* This is the linker script used when building the proxy kernel. */

/*----------------------------------------------------------------------*/
/* Setup                                                                */
/*----------------------------------------------------------------------*/

/* The OUTPUT_ARCH command specifies the machine architecture where the
   argument is one of the names used in the BFD library. More
   specifically one of the entires in bfd/cpu-mips.c */

/* Hardware configuration */
VLMAX_BYTES = 128;  /* Maximum vector length in bytes (j_in_l * word_bytes) */

OUTPUT_ARCH( "riscv" )
ENTRY(_start)

/*----------------------------------------------------------------------*/
/* Program headers                                                      */
/*----------------------------------------------------------------------*/
/* Explicit PHDRS prevent LLD from merging non-adjacent sections into   */
/* one PT_LOAD segment. Each VPU region needs its own segment so the    */
/* simulator can allocate them independently.                           */

PHDRS
{
  text    PT_LOAD;
  tohost  PT_LOAD;
  code    PT_LOAD;
  vpu8    PT_LOAD;
  vpu16   PT_LOAD;
  vpu32   PT_LOAD;
  vpu64   PT_LOAD;
  scalar  PT_LOAD;
  tls     PT_TLS;
}

/*----------------------------------------------------------------------*/
/* Sections                                                             */
/*----------------------------------------------------------------------*/

SECTIONS
{

  /* text: test code section */
  . = 0x80000000;
  .text.init : { *(.text.init) } :text

  . = 0x80001000;
  .tohost : { *(.tohost) } :tohost

  . = ALIGN(0x1000);
  .text : { *(.text) } :code

  /* VPU data segments - large arrays for VPU operations with different element widths */
  /* Align to VLMAX_BYTES for proper vector load/store alignment */
  . = 0x20000000;
  .data.vpu8 : ALIGN(VLMAX_BYTES) {
    *(.data.vpu8)
    *(.rodata.vpu8)
  } :vpu8

  . = 0x20800000;
  .data.vpu16 : ALIGN(VLMAX_BYTES) {
    *(.data.vpu16)
    *(.rodata.vpu16)
  } :vpu16

  . = 0x21000000;
  .data.vpu32 : ALIGN(VLMAX_BYTES) {
    *(.data.vpu32)
    *(.rodata.vpu32)
  } :vpu32

  . = 0x21800000;
  .data.vpu64 : ALIGN(VLMAX_BYTES) {
    *(.data.vpu64)
    *(.rodata.vpu64)
  } :vpu64

  /* Scalar data segment */
  . = 0x10000000;
  .data : { *(.data) } :scalar

  .sdata : {
    __global_pointer$ = . + 0x800;
    *(.srodata.cst16) *(.srodata.cst8) *(.srodata.cst4) *(.srodata.cst2) *(.srodata*)
    *(.sdata .sdata.* .gnu.linkonce.s.*)
  } :scalar

  /* bss segment */
  .sbss : {
    *(.sbss .sbss.* .gnu.linkonce.sb.*)
    *(.scommon)
  } :scalar
  .bss : { *(.bss) } :scalar

  /* thread-local data segment */
  .tdata :
  {
    _tdata_begin = .;
    *(.tdata)
    _tdata_end = .;
  } :scalar :tls
  .tbss :
  {
    *(.tbss)
    _tbss_end = .;
  } :scalar :tls

  /* End of uninitalized data segement */
  _end = .;
}

