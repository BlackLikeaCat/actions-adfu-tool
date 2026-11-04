OUTPUT_ARCH(mips)
ENTRY(_entry)
SECTIONS {
  .entry 0xB4061000 : { KEEP(*(.entry)) }
  .text 0xB4061400 : { *(.text) }
  ASSERT(SIZEOF(.entry) == 0x400, "entry prefix changed")
  ASSERT(ADDR(.text) + SIZEOF(.text) <= 0xB40617C0, "code overlaps owned allocation")
  .data : { *(.data*) *(.sdata*) }
  .bss : { *(.bss*) *(.sbss*) *(COMMON) }
  ASSERT(SIZEOF(.data) == 0 && SIZEOF(.bss) == 0, "unreviewed runtime data")
  .scratch 0xB40617C0 : { LONG(0); . += 36; }
  scratch_guard_low = ADDR(.scratch);
  scratch_pattern = ADDR(.scratch) + 4;
  scratch_guard_high = ADDR(.scratch) + 36;
  ASSERT(SIZEOF(.scratch) == 40, "scratch allocation changed")
  .padding 0xB40617FF : { BYTE(0) }
  /DISCARD/ : { *(.reginfo) *(.MIPS.abiflags) *(.pdr) *(.gnu.attributes) *(.comment) }
}
