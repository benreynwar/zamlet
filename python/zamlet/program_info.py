import re

from elftools.elf.elffile import ELFFile


VPU_SECTION_EW_RE = re.compile(r'\..*\.vpu(\d+)')


def get_program_info(filename='vec-sgemv.riscv'):
    """Extract program information from ELF file automatically."""
    with open(filename, 'rb') as f:
        elf = ELFFile(f)

        sections = []
        for section in elf.iter_sections():
            if not (section['sh_flags'] & 0x2):  # SHF_ALLOC
                continue
            addr = section['sh_addr']
            size = section['sh_size']
            if size == 0:
                continue
            data = section.data()
            if len(data) < size:
                data += bytes(size - len(data))
            m = VPU_SECTION_EW_RE.match(section.name)
            ew = int(m.group(1)) if m else None
            sections.append({
                'address': addr,
                'contents': data,
                'ew': ew,
            })

        entry_point = elf['e_entry']

        symbols = {}
        symbol_table = elf.get_section_by_name('.symtab')
        if symbol_table:
            for symbol in symbol_table.iter_symbols():
                if symbol.name:
                    symbols[symbol.name] = symbol['st_value']

        return {
            'sections': sections,
            'pc': entry_point,
            'tohost': symbols['tohost'],
            'symbols': symbols,
        }
