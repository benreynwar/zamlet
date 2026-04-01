import pytest

# Ignore cocotb test files (they need cocotb's test runner, not pytest)
collect_ignore_glob = ["test_cocotb_memlet.py"]
