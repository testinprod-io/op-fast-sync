import requests
import argparse


L1_BLOCK_CONTRACT_ADDR = '0x4200000000000000000000000000000000000015'


class RPCMethod:
    GetBlockByNumber = 'eth_getBlockByNumber'
    GetBlockByHash = 'eth_getBlockByHash'
    GetTransactionByHash = 'eth_getTransactionByHash'
    GetTransactionReceipt = 'eth_getTransactionReceipt'
    GetBalance = 'eth_getBalance'
    BlockNumber = 'eth_blockNumber'
    GetStorageAt = 'eth_getStorageAt'


def send_json_rpc(url, method, params=None, token=None, timeout=10):
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
    return parser.parse_args()
