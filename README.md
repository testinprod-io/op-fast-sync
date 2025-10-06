# op-fast-sync

## Installation

This project uses `uv` for fast Python package management. Install `uv` first:

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or using pip
pip install uv

# Or using homebrew (macOS)
brew install uv
```

Then install the project dependencies:

```bash
# Create a virtual environment and install dependencies
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -r requirements.txt

# Or install dependencies directly without virtual environment
uv pip install -r requirements.txt
```

## Usage

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
* `--verify-intervals` Enable interval verification (default: True)
* `--no-verify-intervals` Disable interval verification
* `--verify-attempts` Maximum verification attempts per interval (default: 30)
* `--verify-delay` Delay between verification attempts in seconds (default: 2)

## Running the tool

After installing dependencies with `uv`, you can run the tool in several ways:

```bash
# Method 1: Activate virtual environment and run normally
source .venv/bin/activate
python main.py --l1 <l1_url> --l2 <l2_url> --rpc <rpc_url> --engine <engine_url> --jwt-secret <jwt_file>

# Method 2: Using uv to run the script directly (if you installed without venv)
uv run main.py --l1 <l1_url> --l2 <l2_url> --rpc <rpc_url> --engine <engine_url> --jwt-secret <jwt_file>

# Method 3: Using python3 directly (if dependencies are installed globally)
python3 main.py --l1 <l1_url> --l2 <l2_url> --rpc <rpc_url> --engine <engine_url> --jwt-secret <jwt_file>
```

### Example with interval syncing:

```bash
# Using virtual environment (recommended)
source .venv/bin/activate
python main.py \
  --l1 https://your-l1-rpc-url \
  --l2 https://your-l2-rpc-url \
  --rpc http://localhost:8545 \
  --engine http://localhost:8551 \
  --jwt-secret ./jwt-secret.txt \
  --interval 100 \
  --end-block 105235100

# Or using uv run directly
uv run main.py \
  --l1 https://your-l1-rpc-url \
  --l2 https://your-l2-rpc-url \
  --rpc http://localhost:8545 \
  --engine http://localhost:8551 \
  --jwt-secret ./jwt-secret.txt \
  --interval 100 \
  --end-block 105235100
```

## Error Handling and Logging

The tool now includes comprehensive error handling with direct console output:

### Error Logging Features:
- **Direct Console Output**: All errors are printed directly to stdout with clear formatting
- **Detailed Error Information**: Errors include timestamps, block numbers, and full stack traces
- **Retry Logic**: Failed blocks are automatically retried up to 3 times with 1-second delays
- **Clear Error Messages**: Critical errors are displayed with clear formatting and context
- **Comprehensive Coverage**: Error logging covers both payload building and payload application stages

### Error Information Displayed:
Each error includes:
- Timestamp of the error
- Block number that failed
- Error type and message
- Full stack trace
- Payload file path and existence status
- RPC URLs being used (L1 and L2)
- Retry attempt information

### Payload Building Errors:
The payload building stage includes detailed error logging for:
- **L2 Block Retrieval**: Errors when fetching blocks from L2 RPC
- **L1 Block Number Extraction**: Issues with parsing transaction inputs
- **L1 Mixhash Retrieval**: Problems fetching mixhash from L1 RPC
- **Transaction Encoding**: Failures in encoding different transaction types
- **Payload Construction**: Errors in building the final payload structure
- **File Writing**: Issues writing payload files to disk

### Example Payload Building Error:
```
ERROR: Build failed for block 12345:
{
  "block_number": 12345,
  "timestamp": "2024-01-15T10:30:45.123456",
  "error_type": "ConnectionError",
  "error_message": "Connection refused",
  "traceback": "Traceback (most recent call last)...",
  "payload_file": "/path/to/payloads/0x3039.json",
  "l1_rpc_urls": ["http://l1-rpc:8545"],
  "l2_rpc_urls": ["http://l2-rpc:8545"],
  "canyon_time": 0,
  "ecotone_time": 0
}
```

### Example Payload Application Error:
```
ERROR: Apply failed for block 12345:
{
  "block_number": 12345,
  "timestamp": "2024-01-15T10:30:45.123456",
  "error_type": "ConnectionError",
  "error_message": "Connection refused",
  "traceback": "Traceback (most recent call last)...",
  "payload_file": "/path/to/payloads/0x3039.json",
  "engine_url": "http://localhost:8551",
  "payload_exists": true
}
```

## Interval Verification

The tool now includes automatic verification between intervals to ensure each interval is fully synced before proceeding to the next:

### Verification Features:
- **Block Number Checking**: Verifies that the engine has reached the expected block number after each interval
- **Retry Logic**: Attempts verification multiple times with configurable delays
- **Progress Reporting**: Shows current vs expected block numbers during verification
- **Configurable Settings**: Control verification attempts and delays via command line

### Verification Process:
1. After applying all payloads in an interval, the tool calls `eth_blockNumber`
2. Compares the current block number with the expected end block of the interval
3. Retries verification up to the configured number of attempts
4. Provides clear feedback on verification success or failure

### Example Verification Output:
```
✓ Completed applying payloads for interval 1: blocks 1000 to 1999
Verifying interval 1 completion...
Verifying engine has reached block 1999...
Attempt 1/30: Current block: 1995 (0x7cb), Expected: 1999 (0x7cf)
Engine is close (block 1995), waiting for final blocks...
Attempt 2/30: Current block: 1999 (0x7cf), Expected: 1999 (0x7cf)
✓ Verification successful: Engine has reached block 1999 >= 1999
✓ Interval 1 verification successful: blocks 1000 to 1999
```

### Disabling Verification:
If you want to disable interval verification for faster syncing:
```bash
python main.py --no-verify-intervals [other args...]
```

### Customizing Verification:
```bash
# Custom verification settings
python main.py --verify-attempts 60 --verify-delay 5 [other args...]
```
