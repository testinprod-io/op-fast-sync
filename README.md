# op-fast-sync

## required args

The following args are required:

* `--l1` Synced ETH L1 RPC URL (geth) e.g., http://geth:8545
* `--l2` Synced Optimism RPC URL (op-geth) e.g., http://good-op-geth:8545
* `--rpc` Target Optimism RPC URL (op-geth), e.g., http://unsynced-op-geth:8545
* `--engine` Target Optimism AuthRPC URL (op-geth), e.g., http://unsynced-op-geth:8551
* `--jwt-secret` Target Optimism AuthRPC JWT Secret file
