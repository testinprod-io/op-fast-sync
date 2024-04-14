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
    parser.add_argument('--ecotone-block-number', dest='ecotone_block_number', default=0, type=int)
    parser.add_argument('--canyon-time', dest='canyon_time', default=0, type=int)
    return parser.parse_args()
