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

pytest_args = list(sys.argv[1:])
log_level = os.environ.get("LOG_LEVEL")
if log_level:
    pytest_args.extend([
        "-o", "log_cli=true",
        "--log-cli-level", log_level.upper(),
    ])

exit_code = pytest.main(pytest_args, plugins=plugins)
if (
    total_shards > 0
    and shard_index > 0
    and exit_code == pytest.ExitCode.NO_TESTS_COLLECTED
):
    exit_code = pytest.ExitCode.OK
sys.exit(exit_code)
