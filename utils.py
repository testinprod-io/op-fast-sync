import requests
import argparse
import threading
import time


L1_BLOCK_CONTRACT_ADDR = '0x4200000000000000000000000000000000000015'


class RateLimiter:
    """
    Leaky bucket rate limiter for RPC requests.

    This ensures smooth rate limiting without large bursts that could
    exceed provider limits when multiple processes make requests simultaneously.
    """

    def __init__(self, max_requests_per_second=300):
        self.max_requests = max_requests_per_second
        self.min_interval = 1.0 / max_requests_per_second  # Minimum time between requests
        self.last_request_time = 0
        self.lock = threading.Lock()

    def acquire(self):
        """Acquire permission to make a request. Blocks if rate limit would be exceeded."""
        with self.lock:
            now = time.time()
            time_since_last = now - self.last_request_time

            # If not enough time has passed, calculate wait time
            if time_since_last < self.min_interval:
                wait_time = self.min_interval - time_since_last
                self.last_request_time = now + wait_time
            else:
                wait_time = 0
                self.last_request_time = now

        # Sleep outside the lock to allow other threads to proceed
        if wait_time > 0:
            time.sleep(wait_time)


class RateLimiterManager:
    """Manages separate rate limiters for each RPC endpoint URL."""

    def __init__(self, default_rate=300):
        self.default_rate = default_rate
        self.limiters = {}
        self.lock = threading.Lock()

    def get_limiter(self, url):
        """Get or create a rate limiter for a specific URL."""
        # Extract base URL (remove trailing slashes, query params, etc.)
        base_url = url.split('?')[0].rstrip('/')

        with self.lock:
            if base_url not in self.limiters:
                self.limiters[base_url] = RateLimiter(max_requests_per_second=self.default_rate)
            return self.limiters[base_url]

    def set_rate(self, rate):
        """Update the rate limit for all current and future limiters."""
        with self.lock:
            self.default_rate = rate
            for limiter in self.limiters.values():
                limiter.max_requests = rate
                # Don't reset tokens - let them naturally refill

    def get_stats(self):
        """Get statistics about tracked endpoints."""
        with self.lock:
            return {
                'default_rate': self.default_rate,
                'num_endpoints': len(self.limiters),
                'endpoints': list(self.limiters.keys())
            }


# Global rate limiter manager - 250 requests per second per endpoint (default)
# Conservative default to account for burst traffic from multiprocessing
_rate_limiter_manager = RateLimiterManager(default_rate=250)


class RPCMethod:
    GetBlockByNumber = 'eth_getBlockByNumber'
    GetBlockByHash = 'eth_getBlockByHash'
    GetTransactionByHash = 'eth_getTransactionByHash'
    GetTransactionReceipt = 'eth_getTransactionReceipt'
    GetBalance = 'eth_getBalance'
    BlockNumber = 'eth_blockNumber'
    GetStorageAt = 'eth_getStorageAt'


def send_json_rpc(url, method, params=None, token=None, timeout=10):
    # Acquire rate limit permission for this specific URL before making request
    limiter = _rate_limiter_manager.get_limiter(url)
    limiter.acquire()

    headers = {
        'Content-Type': 'application/json',
    }
    if token is not None:
        headers['Authorization'] = f'Bearer {token}'
    data = {
        'jsonrpc': '2.0',
        'method': method,
        'params': [] if params is None else params,
        'id': 1
    }
    res = requests.post(url, json=data, headers=headers, timeout=timeout)

    # Check if response is empty
    if not res.text:
        raise Exception(f"Empty response from {url} for method {method}")

    # Try to parse JSON
    try:
        response_json = res.json()
    except Exception as e:
        raise Exception(f"Failed to parse JSON response from {url}: {res.text[:200]}")

    # Check for JSON-RPC error
    if 'error' in response_json:
        error = response_json['error']
        raise Exception(f"RPC error: {error.get('message', error)}")

    if 'result' not in response_json:
        raise Exception(f"No 'result' field in response: {response_json}")

    return response_json['result']


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--payload', dest='payload_dir', default='./payloads')
    parser.add_argument('--l1', dest='l1_rpc_urls', action='append', required=True)
    parser.add_argument('--l2', dest='l2_rpc_urls', action='append', required=True)
    parser.add_argument('--rpc', dest='rpc_url', required=True)
    parser.add_argument('--engine', dest='engine_url', required=True)
    parser.add_argument('--batch-size', dest='batch_size', default=100, type=int)
    parser.add_argument('--jwt-secret', dest='jwt_secret', default='./jwt-secret.txt')
    parser.add_argument('--num-proc', dest='num_proc', default=32, type=int)
    parser.add_argument('--logging', action='store_true', default=False)
    parser.add_argument('--canyon-time', dest='canyon_time', default=0, type=int)
    parser.add_argument('--ecotone-time', dest='ecotone_time', default=0, type=int)
    parser.add_argument('--isthmus-time', dest='isthmus_time', default=0, type=int)
    parser.add_argument('--block-end', dest='block_end', default=None, type=int, help='End syncing at this block number instead of latest block from RPC')
    parser.add_argument('--concurrent', action='store_true', default=True, help='Enable concurrent building and applying (default: True)')
    parser.add_argument('--sequential', action='store_true', default=False, help='Force sequential mode (build all, then apply all)')
    parser.add_argument('--trigger-sync', dest='trigger_sync', default=None, type=int, help='Trigger EL sync by building and applying a single block, then exit')
    parser.add_argument('--trigger-sync-list', dest='trigger_sync_list', default=None, type=str, help='Trigger EL sync for a list of blocks sequentially (comma-separated), waiting for each to sync before proceeding. Example: 10,20,30')
    parser.add_argument('--rate-limit', dest='rate_limit', default=250, type=int, help='Maximum RPC requests per second per endpoint (default: 250, safer than 300 to account for burst traffic)')
    return parser.parse_args()
