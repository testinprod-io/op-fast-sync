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
    return res.json()['result']


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
    parser.add_argument('--interval', dest='interval', default=1000, type=int, help='Number of blocks to sync in each interval')
    parser.add_argument('--end-block', dest='end_block', type=int, help='Block number to stop syncing at (overrides latest block)')
    parser.add_argument('--verify-intervals', dest='verify_intervals', action='store_true', default=True, help='Verify block numbers between intervals (default: True)')
    parser.add_argument('--no-verify-intervals', dest='verify_intervals', action='store_false', help='Disable interval verification')
    parser.add_argument('--verify-attempts', dest='verify_attempts', default=30, type=int, help='Maximum verification attempts per interval (default: 30)')
    parser.add_argument('--verify-delay', dest='verify_delay', default=2, type=int, help='Delay between verification attempts in seconds (default: 2)')
    parser.add_argument('--finalize-intervals', dest='finalize_intervals', action='store_true', default=True, help='Enable interval finalization (default: True)')
    parser.add_argument('--no-finalize-intervals', dest='finalize_intervals', action='store_false', help='Disable interval finalization')
    parser.add_argument('--finalize-attempts', dest='finalize_attempts', default=3, type=int, help='Maximum finalization attempts per interval (default: 3)')
    return parser.parse_args()
