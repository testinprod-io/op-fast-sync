import io
import json
import os
import pprint
import random
import sys
import time
from multiprocessing import Pool

import rlp
from tqdm import tqdm

from utils import send_json_rpc, RPCMethod, L1_BLOCK_CONTRACT_ADDR

pp = pprint.PrettyPrinter(indent=2)


class PayloadBuilder:
    def __init__(self, payload_dir, l1_rpc_urls, l2_rpc_urls, logging=False):
        self.payload_dir = payload_dir
        self.l1_rpc_urls = l1_rpc_urls
        self.l2_rpc_urls = l2_rpc_urls
        self.logging = logging

    def _get_l1_rpc_url(self):
        return random.choice(self.l1_rpc_urls)

    def _get_l2_rpc_url(self):
        return random.choice(self.l2_rpc_urls)

    @staticmethod
    def _encode_access_list(access_list):
        if access_list is None:
            return []
        encoded = []
        for at in access_list:
            encoded.append([
                bytes.fromhex(at['address'][2:]),
                [
                    bytes.fromhex(key[2:]) for key in at['storageKeys']
                ]
            ])
        return encoded

    def build(self, n):
        l2_block_number = hex(n)
        payload_file = os.path.join(self.payload_dir, f'{l2_block_number}.json')
        if os.path.exists(payload_file):
            return

        l2_rpc_url = self._get_l2_rpc_url()

        # 1. get block from l2
        l2_block = send_json_rpc(l2_rpc_url, RPCMethod.GetBlockByNumber, params=[l2_block_number, True])

        # 2. get l1 block number
        res = send_json_rpc(l2_rpc_url, RPCMethod.GetStorageAt, params=[L1_BLOCK_CONTRACT_ADDR, hex(0), l2_block_number])
        l1_block_number = hex(int(res[-16:], 16))

        # 3. get l1 mixhash
        res = send_json_rpc(self._get_l1_rpc_url(), RPCMethod.GetBlockByNumber, params=[l1_block_number, False])
        prevRandao = res['mixHash']

        # 4. encode txs
        encoded_txs = []

        for tx in l2_block['transactions']:
            type = tx['type'][2:]
            to = tx.get('to', '0x')
            if to is not None:
                to = bytes.fromhex(to[2:])
            if type == '1':
                encoded_tx = '0x' + (
                    bytes.fromhex('01') +
                    rlp.encode([
                        int(tx['chainId'], 16),
                        int(tx['nonce'], 16),
                        int(tx['gasPrice'], 16),
                        int(tx['gas'], 16),
                        to,
                        int(tx['value'], 16),
                        bytes.fromhex(tx['input'][2:]),
                        self._encode_access_list(tx.get('accessList')),
                        int(tx['v'], 16),
                        int(tx['r'], 16),
                        int(tx['s'], 16),
                    ])
                ).hex()
            elif type == '2':
                encoded_tx = '0x' + (
                    bytes.fromhex('02') +
                    rlp.encode([
                        int(tx['chainId'], 16),
                        int(tx['nonce'], 16),
                        int(tx['maxPriorityFeePerGas'], 16),
                        int(tx['maxFeePerGas'], 16),
                        int(tx['gas'], 16),
                        to,
                        int(tx['value'], 16),
                        bytes.fromhex(tx['input'][2:]),
                        self._encode_access_list(tx.get('accessList')),
                        int(tx['v'], 16),
                        int(tx['r'], 16),
                        int(tx['s'], 16),
                    ])
                ).hex()
            elif type == '7e':
                encoded_tx = '0x' + (
                    bytes.fromhex(type) +
                    rlp.encode([
                        bytes.fromhex(tx['sourceHash'][2:]),
                        bytes.fromhex(tx['from'][2:]),
                        to,
                        int(tx['mint'], 16),
                        int(tx['value'], 16),
                        int(tx['gas'], 16),
                        int(tx.get('isSystemTx', 0)),
                        bytes.fromhex(tx['input'][2:]),
                    ])
                ).hex()
            else:
                encoded_tx = '0x' + rlp.encode([
                    int(tx['nonce'], 16),
                    int(tx['gasPrice'], 16),
                    int(tx['gas'], 16),
                    to,
                    int(tx['value'], 16),
                    bytes.fromhex(tx['input'][2:]),
                    int(tx['v'], 16),
                    int(tx['r'], 16),
                    int(tx['s'], 16),
                ]).hex()
            encoded_txs.append(encoded_tx)

        # 5. build payload
        payload = {
            'parentHash': l2_block['parentHash'],
            'feeRecipient': '0x4200000000000000000000000000000000000011',
            'stateRoot': l2_block['stateRoot'],
            'receiptsRoot': l2_block['receiptsRoot'],
            'logsBloom': l2_block['logsBloom'],
            'prevRandao': prevRandao,
            'blockNumber': l2_block['number'],
            'gasLimit': l2_block['gasLimit'],
            'gasUsed': l2_block['gasUsed'],
            'timestamp': l2_block['timestamp'],
            'extraData': l2_block['extraData'],
            'baseFeePerGas': l2_block['baseFeePerGas'],
            'blockHash': l2_block['hash'],
            'transactions': encoded_txs,
        }

        with open(payload_file, 'w') as f:
            json.dump(payload, f)

        return True

    def job(self, n):
        for _ in range(3):
            try:
                return self.build(n)
            except:
                pass
        print(f"FAILED: {n}")

    def run_multiproc(self, start, end, num_proc):
        p = Pool(num_proc)
        pbar = tqdm(p.imap_unordered(self.job, range(start, end + 1)), total=end - start + 1, file=io.StringIO() if self.logging else sys.stdout)
        logged_at = 0
        for _ in pbar:
            now = time.time()
            if self.logging and now > logged_at + 10:
                data = pbar.format_dict
                print(f'building payload | {data["n"]}/{data["total"]} | elapsed: {time.strftime("%H:%M:%S", time.gmtime(data["elapsed"]))}')
                logged_at = now

        p.close()
        p.join()
