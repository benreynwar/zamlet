import subprocess
import re


def parse_objdump(binary_path):
    """Parse objdump output into a dict mapping PC -> (bytes, instruction_text)"""
    result = subprocess.run(
        ['riscv64-none-elf-objdump', '-d', binary_path],
        capture_output=True,
        text=True,
        check=True
    )

    trace = {}

    for line in result.stdout.split('\n'):
        # Match lines like: "  80000000:	4081                	li	ra,0"
        # or: "  80000002:	02810313          	addi	t1,sp,40"
        match = re.match(r'\s*([0-9a-f]+):\s+([0-9a-f]+)\s+(.+)', line)
        if match:
            pc = int(match.group(1), 16)
            instr_bytes = match.group(2)
            instr_text = match.group(3).strip()

            # Parse the hex bytes
            bytes_int = int(instr_bytes, 16)

            trace[pc] = {
                'bytes': bytes_int,
                'text': instr_text,
                'num_bytes': len(instr_bytes) // 2
            }

    return trace


def check_instruction(trace, pc, actual_bytes, actual_text):
    """Compare actual execution against reference trace"""
    if pc not in trace:
        logger.error(f"WARNING: PC {hex(pc)} not in objdump trace")

    expected = trace[pc]

    # Compare bytes (mask to appropriate size)
    if expected['num_bytes'] == 2:
        actual_bytes_masked = actual_bytes & 0xFFFF
        expected_bytes = expected['bytes'] & 0xFFFF
    else:
        actual_bytes_masked = actual_bytes & 0xFFFFFFFF
        expected_bytes = expected['bytes']

    if actual_bytes_masked != expected_bytes:
        return (f"BYTE MISMATCH at {hex(pc)}: "
                f"expected bytes {hex(expected_bytes)} ({expected['text']}), "
                f"got {hex(actual_bytes_masked)} ({actual_text})")

    # Also compare disassembly text as a sanity check
    # Strip comments (anything after #) and symbol annotations (anything after <) before comparing
    expected_text_clean = expected['text'].split('#')[0].split('<')[0].strip()
    actual_text_clean = actual_text.split('#')[0].split('<')[0].strip()

    expected_normalized = ' '.join(expected_text_clean.split())
    actual_normalized = ' '.join(actual_text_clean.split())

    # Skip text comparison when objdump doesn't recognize the instruction
    # (outputs ".insn" for custom opcodes that our decoder knows about)
    if expected_normalized != actual_normalized and not expected_normalized.startswith('.insn'):
        return (f"DISASM MISMATCH at {hex(pc)}: "
                f"expected '{expected_text_clean}', "
                f"got '{actual_text_clean}' "
                f"(bytes={hex(actual_bytes_masked)})")

    return None
