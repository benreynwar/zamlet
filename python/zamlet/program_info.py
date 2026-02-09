from elftools.elf.elffile import ELFFile


def get_program_info(filename='vec-sgemv.riscv'):
    """Extract program information from ELF file automatically."""
    with open(filename, 'rb') as f:
        elf = ELFFile(f)

        segments = []
        for segment in elf.iter_segments():
            if segment['p_type'] == 'PT_LOAD':
                vaddr = segment['p_vaddr']
                memsz = segment['p_memsz']
                filesz = segment['p_filesz']
                offset = segment['p_offset']

                f.seek(offset)
                data = f.read(filesz)

                if memsz > filesz:
                    data += bytes(memsz - filesz)

                segments.append({
                    'address': vaddr,
                    'contents': data,
                })

        entry_point = elf['e_entry']

        symbols = {}
        symbol_table = elf.get_section_by_name('.symtab')
        if symbol_table:
            for symbol in symbol_table.iter_symbols():
                if symbol.name:
                    symbols[symbol.name] = symbol['st_value']

        return {
            'segments': segments,
            'pc': entry_point,
            'tohost': symbols['tohost'],
            'symbols': symbols,
        }
