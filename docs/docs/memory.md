# Memory Mapping

There are several different kinds of memory mapping going on in the zamlet hardware.

**Virtual Address -> Alpha Physical Address**

The standard mapping done by the TLB.
Only changes the address bits above the page table size.

**Alpha Physical Address -> Beta Physical Address**

This is a permutation of the bytes in a vector-line (number of lanes * word size).  It depends on
the 'element-width' configuration of the page, which is a configuration variable stored in a
page table.  It will be discussed more later.

**Beta Physical Address -> Gamma Physical Address**

This is a permutation of the order of the words in a vector line.  The purpose of this is to arrange
the words in the grid so that words close in the vector line are also close in the 2-dimensional
mesh.

**Gamma Physical Address -> (DRAM instance, DRAM address)**

Maps the address space into the address space of the individual DRAMs.

# Caching

The cache is distributed across the jamlets. Each word of memory from a DRAM is bound to a specific
jamlet, which is responsible for caching it.  All requests for that word of memory must pass through
that jamlet.  This makes memory accesses fast and efficient when the accesses are aligned to the
vector-line width, and very inefficient when they are not.

# Alpha <-> Beta Mapping #

In the RISC-V vector extension the elements are arranged in a vector consecutively.
This means that if we have 64-bit words and 16-bit elements and a 4 word vector we would have.

        |---Word 1--|---Word 2--|---Word 3--|---Word 4--|
         e0 e1 e2 e3 e4 e5 e6 e7 e8 e9 eA eB eC eD eE eF

And if we have another vector with elements of size 32-bit using LMUL=2 it would be arranged as

        |---Word 1--|---Word 2--|---Word 3--|---Word 4--|
         f0    f1    f2    f3    f4    f5    f6    f7
         f8    f9    fA    fB    fC    fD    fE    fF

This is a problem if we want to add these two vectors, and we have one word distributed in each lane.
Adding e0 with f0 is no problem, adding e1 and f1 is ok, but when we try to add e2 with f2 we
see that they are in different lanes, and so we would have to do lane-to-lane communication to support
a simple vector add.

We can't change how the elements are laid out in the address space since that is defined in the riscv
vector extension, however we can change how they are physically laid out in the memory.  Each page
is assigned an 'element-width' property, which determines how the address space maps to the bytes of
the physical page.

For example if the page has an 'element-width' of 16-bits then the bytes are arranged as

            |----Word 1-------------|----Word 2-------------|----Word 3-------------|----Word 4-------------|
    address  00 01 08 09 10 11 18 19 02 03 0A 0B 12 13 1A 1B 04 05 0C 0D 14 15 1C 1D 06 07 0E 0F 16 17 1E 1F

Such that when a elements of width 16 (matching the page element-width) are placed in the memory they
are arranged as:

Page layout with element width 16 bits

            |----Word 1-------------|----Word 2-------------|----Word 3-------------|----Word 4-------------|
    address  00 01 08 09 10 11 18 19 02 03 0A 0B 12 13 1A 1B 04 05 0C 0D 14 15 1C 1D 06 07 0E 0F 16 17 1E 1F
    element  e0    e4    e8    eC    e1    e5    e9    eD    e2    e6    eA    eE    e3    e7    eB    eF

Page layout with element width 32 bits

            |----Word 1-------------|----Word 2-------------|----Word 3-------------|----Word 4-------------|
    address  00 01 02 03 10 11 12 13 04 05 06 07 14 15 16 17 08 09 0A 0B 18 19 1A 1B 0C 0D 0E 0F 1C 1D 1E 1F
    element  f0          f4          f1          f5          f2          f6          f3          f7      
             f8          fC          f9          fD          fA          fE          fB          fF      

We can see that if the if a vector of elements of width 16 is placed in a page with element-width 16, and
a vector with elements of width 32 is placed in a page with element-width 32 then the elements contained in
each physical word are the same.

# Beta <-> Gamma Mapping

The jamlets, when considered in address space order, are laid out in a Moore curve on the 2D mesh.  The
words of the address space are interleaved across the jamlets following this pattern.
This means that two words close in the address space will also be close physically on the mesh.

# Gamma <-> DRAM Mapping

Each kamlet has a dedicated memlet which communicates with a dedicated DRAM.  The words of a DRAM
cache line are interleaved across the jamlets of that kamlet.
