# op-fast-sync

## required args

The following args are required:

* `--l1` Synced ETH L1 RPC URL (geth) e.g., http://geth:8545
* `--l2` Synced Optimism RPC URL (op-geth) e.g., http://good-op-geth:8545
* `--rpc` Target Optimism RPC URL (op-geth), e.g., http://unsynced-op-geth:8545
* `--engine` Target Optimism AuthRPC URL (op-geth), e.g., http://unsynced-op-geth:8551
* `--jwt-secret` Target Optimism AuthRPC JWT Secret file

## optional args

* `--interval` Number of blocks to sync in each interval (default: 1000)
* `--end-block` Block number to stop syncing at (overrides latest block)
* `--batch-size` Batch size for payload application (default: 100)
* `--num-proc` Number of processes for payload building (default: 32)
* `--payload` Payload directory (default: ./payloads)
* `--logging` Enable logging mode
* `--canyon-time` Canyon fork timestamp (default: 0)
* `--ecotone-time` Ecotone fork timestamp (default: 0)
