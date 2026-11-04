/* H9: exactly two 32 KiB passes, 32-byte chunks, no host-selected targets. */
.set noreorder
.set noat
.set nomacro
.section .entry,"ax",@progbits
.globl _entry
_entry:
    beq $zero, $zero, start
    nop
    .space 0x3f8, 0

.section .text,"ax",@progbits
.globl start, terminal, pre_poll, post_poll, send_response, code_end
.globl status_read, status_write, prid_read, config0_read, config1_read, config2_read, config3_read
.globl initialize_owned, pattern_store, sample_copy, sample_words, sample_after, response_done, transmit
start:
status_read:
    mfc0 $t0, $12, 0
    .rept 8
    nop
    .endr
    addu $s6, $t0, $zero
    addu $s7, $sp, $zero
    lui $t1, 0xffff
    ori $t1, $t1, 0xfffe
    and $t0, $t0, $t1
status_write:
    mtc0 $t0, $12, 0
    .rept 8
    nop
    .endr
prid_read:
    mfc0 $s0, $15, 0
    .rept 8
    nop
    .endr
config0_read:
    mfc0 $s1, $16, 0
    .rept 8
    nop
    .endr
    ori $s2, $zero, 0
    ori $s3, $zero, 0
    ori $s4, $zero, 0
    ori $s5, $zero, 3
    bgez $s1, initialize_owned
    nop
config1_read:
    mfc0 $s2, $16, 1
    .rept 8
    nop
    .endr
    ori $s5, $s5, 4
    bgez $s2, initialize_owned
    nop
config2_read:
    mfc0 $s3, $16, 2
    .rept 8
    nop
    .endr
    ori $s5, $s5, 8
    bgez $s3, initialize_owned
    nop
config3_read:
    mfc0 $s4, $16, 3
    .rept 8
    nop
    .endr
    ori $s5, $s5, 16
initialize_owned:
    lui $t5, 0xb406
    ori $t5, $t5, 0x17c0
    lui $t8, 0xa65c
    ori $t8, $t8, 0x39d2
    lui $t9, 0x5aa5
    ori $t9, $t9, 0xc33c
    sw $t8, 0($t5)
    sw $t9, 36($t5)
    addiu $a0, $t5, 4
    ori $t6, $zero, 0
pattern_store:
    sb $t6, 0($a0)
    addiu $t6, $t6, 1
    addiu $a0, $a0, 1
    sltiu $t7, $t6, 32
    bne $t7, $zero, pattern_store
    nop
    ori $v0, $zero, 0
    lui $a1, 0xbfc0
transmit:
    lui $t2, 0xb029
    lui $t3, 0x0010
pre_poll:
    lbu $t4, 0x17($t2)
    andi $t4, $t4, 2
    beq $t4, $zero, send_response
    nop
    addiu $t3, $t3, -1
    bne $t3, $zero, pre_poll
    nop
    beq $zero, $zero, terminal
    nop
send_response:
    .include "identity.inc"
    beq $v0, $zero, payload_words
    nop
    sw $v0, 0x88($t2)
    sw $v1, 0x88($t2)
    addu $t6, $a1, $zero
    sw $t6, 0x88($t2)
    ori $t6, $zero, 32
    sw $t6, 0x88($t2)
payload_words:
    sw $s0, 0x88($t2)
    sw $s1, 0x88($t2)
    sw $s2, 0x88($t2)
    sw $s3, 0x88($t2)
    sw $s4, 0x88($t2)
    sw $s5, 0x88($t2)
    sw $s6, 0x88($t2)
    sw $s7, 0x88($t2)
    ori $t0, $zero, 64
    beq $v0, $zero, commit_response
    nop
    ori $t0, $zero, 80
commit_response:
    sb $t0, 0x14($t2)
    sb $zero, 0x15($t2)
    sb $zero, 0x17($t2)
    lui $t3, 0x0010
post_poll:
    lbu $t4, 0x17($t2)
    andi $t4, $t4, 2
    beq $t4, $zero, response_done
    nop
    addiu $t3, $t3, -1
    bne $t3, $zero, post_poll
    nop
terminal:
    beq $zero, $zero, terminal
    nop
response_done:
    beq $v0, $zero, advance_sample
    nop
    beq $v1, $zero, terminal
    nop
    ori $t6, $zero, 2048
    beq $v0, $t6, terminal
    nop
    addiu $a1, $a1, 32
    ori $t6, $zero, 1024
    bne $v0, $t6, advance_sample
    nop
    lui $a1, 0xbfc0
advance_sample:
    addiu $v0, $v0, 1
sample_copy:
    lw $t6, 0($t5)
    xor $v1, $t6, $t8
    lw $t6, 36($t5)
    xor $t6, $t6, $t9
    or $v1, $v1, $t6
sample_words:
    lw $s0, 0($a1)
    lw $s1, 4($a1)
    lw $s2, 8($a1)
    lw $s3, 12($a1)
    lw $s4, 16($a1)
    lw $s5, 20($a1)
    lw $s6, 24($a1)
    lw $s7, 28($a1)
sample_after:
    lw $t6, 0($t5)
    xor $t6, $t6, $t8
    or $v1, $v1, $t6
    lw $t6, 36($t5)
    xor $t6, $t6, $t9
    or $v1, $v1, $t6
    sltiu $v1, $v1, 1
    beq $zero, $zero, transmit
    nop
code_end:
