# Stripe

The hardware is organized around chunks of data of size `n_lanes * word_width` which we refer to as 'stripes'.
A vector register with LMUL=1 contains a stripe.
If we have a 32x32 mesh of lanes, a stripe would then be 1024 * 8 B = 8 KiB.

## Vector Register File

A stripe of data in the cache is partitioned across the lanes in exactly the same way that a vector register is partioned across
the vector register file slices in the lanes.  The exact byte ordering will depend on the element-width that the hardware uses for
the stripe, but this effect will be identical in the cache, in memory and in the vector register.  Because of this, loading or storing a
stripe-aligned, element-width matched vector moves no data between lanes, it only moves data between the local cache SRAM and the vector
register file slice.

## Stripe vs Cache Line vs Page

A stripe is an aligned chunk of memory as described above.  A page is either a sequence of consecutive stripes, or a fraction of a stripe depending on
whether the page is smaller or larger than a stripe. If the page is smaller then it is required that pages are allocated in stripe-sized groups.

Each cache line contains a fraction of several stripes.  This is because the lanes (jamlets) are organized into lane-groups (kamlets)
and each kamlet has an independent memory and cache table.  The physical memory addresses are
striped across kamlets. If each kamlet has `j_in_k` jamlets, then we have `j_in_k` words from the first kamlet, followed by `j_in_k` words from the
second kamlet and so on.

[Insert diagram here showing a mesh with cache lines, pages, and stripes illustrated]

## Cache Ownership

Each word in the physical vector memory has a particular jamlet's SRAM that is used when it's cached.  If a different jamlet
needs to access this data they will send a message requesting this data.  This means that when a load or a store is aligned with a stripe (and the element width
matches) then the data movement between cache and register file is purely local, but when the access is not aligned it requires cross-mesh messaging.

[Diagram showing data in the memory, and how that maps to data in the caches]
[Also show a diagram illustrating a jamlet requesting data from another jamlet, and then that kamlet retrieving the cache line from the memory]


## Element Width Per Stripe

The hardware tracks what element-width each stripe of data in the vector register file and in memory were written with.  The data is stored such that
the first element is mapped to lane 0, the second element is mapped to lane 1 and so on.  This means that the ordering of logical bytes to physical bytes
depends on the element-width with which the data was written.  For mask data (element width is 1 bit) the bit ordering is modified in the same way.

[A diagram showing how data is organized in the register file depending on ew]

## Unaligned Or Mismatched Element Width Accesses

When loads or stores are aligned to the stripe, and the element width of the instruction matches the element width of the source stripe the data movement
is entirely local.  Similarly when arithmetic instructions have an element width that matches the source operands in the vector register file, all
operands are present in the local lane.  This is typically the case.

When the access is not aligned to the stripe with a matching element width, we need rearrangement of the data at the mesh level.  Jamlets will need to
send messages to other jamlets requesting data.  This is a performance cliff.
The common case has purely local data movement (performance increases linearly with the nubmer of lanes), while the rare case is catastrophic (performance only
increases with the squareroot of the number of lanes).

[Need actual data numbers here, rather than guessing]

We move abruptly from a regime where data movement is negligible, to where it will totally limit the performance of the system.
This architecture is based on the assumption that we can find ways to avoid the performance cliff and keep data movement mostly local.

## Summary

The riscv vector specification specifies that elements in a vector are organized in memory sequentially. This is necessary to make the ISA independent
of the vector length and works well when the vector register file
is centralized, however it makes it difficult to scale the vector processing unit to large sizes.  In this architecture we get around this by tracking
the element-width of each stripe of data in the vector memory and the vector register file. The element-width determines the byte ordering of the data
such that elements are local to the corresponding lane.  This results in high performance when accesses are aligned to the stripe, and when the required
element width matches the used element width, but results in very poor performance when this is not the case.

