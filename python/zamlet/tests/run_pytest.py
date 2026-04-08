import os
import sys
import pytest


class BazelShardPlugin:
    """Select tests based on Bazel's TEST_SHARD_INDEX / TEST_TOTAL_SHARDS."""

    def __init__(self, shard_index, total_shards):
        self.shard_index = shard_index
        self.total_shards = total_shards

    def pytest_collection_modifyitems(self, items):
        selected = [item for i, item in enumerate(items)
                    if i % self.total_shards == self.shard_index]
        items[:] = selected


plugins = []
total_shards = int(os.environ.get('TEST_TOTAL_SHARDS', '0'))
if total_shards > 0:
    shard_index = int(os.environ.get('TEST_SHARD_INDEX', '0'))
    plugins.append(BazelShardPlugin(shard_index, total_shards))
    status_file = os.environ.get('TEST_SHARD_STATUS_FILE')
    if status_file:
        open(status_file, 'a').close()

sys.exit(pytest.main(sys.argv[1:], plugins=plugins))
