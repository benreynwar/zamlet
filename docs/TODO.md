# TODO

- [ ] Add a Bazel macro that combines genrule + cocotb_binary + py_library + cocotb_test
      to reduce boilerplate in test BUILD files.
- [ ] Packet header bit packing: ReadMemWordHeader and WriteMemWordHeader fields exceed
      the 64-bit header budget. element_index alone is 22 bits but only ~10 bits remain
      after TaggedHeader. Need to decide if 64-bit limit is firm, which fields can be
      derived, and whether some fields only apply to certain message subtypes. Added
      writeset_ident to both headers without resolving packing. When no_response=True
      on WriteMemWordHeader, source_x/source_y (16 bits) are unused and could carry
      writeset_ident in hardware.
- [ ] Replace store-ew-mismatch workaround (store to scratch memory + reload at new ew)
      with a dedicated register-to-register ew remap kinstr using J2J messages.
      Currently in `vloadstore` in `lamlet/unordered.py`.
- [ ] When an instruction writes to a register with a different ew than the existing
      contents, and doesn't update all elements (e.g. masked or vl < vlmax), the
      unwritten elements still have the old ew layout. May need to ew-remap the old
      contents before the partial write so everything is consistent.
