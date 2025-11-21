import io
import json
import os
import pprint
import random
import sys
import time
from multiprocessing import Pool

import rlp
import eth_abi
from tqdm import tqdm

from utils import send_json_rpc, RPCMethod, L1_BLOCK_CONTRACT_ADDR

pp = pprint.PrettyPrinter(indent=2)
L1_INFO_TX_TYPES = ['uint64', 'uint64', 'uint256', 'bytes32', 'uint64', 'bytes32', 'uint256', 'uint256']

class PayloadBuilder:
    def __init__(self, payload_dir, l1_rpc_urls, l2_rpc_urls, canyon_time, ecotone_time, isthmus_time, logging=False, shared_state=None):
        self.payload_dir = payload_dir
        self.l1_rpc_urls = l1_rpc_urls
        self.l2_rpc_urls = l2_rpc_urls
        self.canyon_time = canyon_time
        self.ecotone_time = ecotone_time
        self.isthmus_time = isthmus_time
        self.logging = logging
        self.shared_state = shared_state

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
            return True  # Return True for already-built blocks

        l2_rpc_url = self._get_l2_rpc_url()

        # 1. get block from l2
        l2_block = send_json_rpc(l2_rpc_url, RPCMethod.GetBlockByNumber, params=[l2_block_number, True])
        txInput = l2_block['transactions'][0]['input']
        # 2. get l1 block number
        if int(l2_block['timestamp'], 16) >= self.ecotone_time:
            l1_block_number = hex(int.from_bytes(bytes.fromhex(txInput[2:])[28:36], 'big'))
        else:
            l1_block_number = hex(eth_abi.decode(L1_INFO_TX_TYPES, bytes.fromhex(txInput[10:]))[0])

        l1_rpc_url = self._get_l1_rpc_url()
        # 3. get l1 mixhash
        res = send_json_rpc(l1_rpc_url, RPCMethod.GetBlockByNumber, params=[l1_block_number, False])
        prevRandao = res['mixHash']
        # 4. encode txs
        encoded_txs = []

        for tx in l2_block['transactions']:
            type = tx['type'][2:]
            to = tx.get('to')
            if to is None:
                to = b''
            else:
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

        payloadArray = [payload]

        if int(l2_block['timestamp'], 16) >= self.canyon_time:
            payload['withdrawals'] = []
            payloadArray = [payload]

        if int(l2_block['timestamp'], 16) >= self.ecotone_time:
            payload['blobGasUsed'] = l2_block['blobGasUsed']
            payload['excessBlobGas'] = l2_block['excessBlobGas']
            payloadArray = [payload, [], l2_block['parentBeaconBlockRoot']]

        if int(l2_block['timestamp'], 16) >= self.isthmus_time:
            payload['withdrawalsRoot'] = l2_block['withdrawalsRoot']
            # For Isthmus, we need to add empty executionRequests array as 4th parameter for V4
            payloadArray = [payload, [], l2_block['parentBeaconBlockRoot'], []]

        with open(payload_file, 'w') as f:
            json.dump(payloadArray, f)

        return True

    def job(self, n):
        for attempt in range(3):
            try:
                result = self.build(n)
                # Return success with block number so main thread can update shared state
                return (n, True, result)
            except Exception as e:
                if attempt == 2:  # Last attempt
                    print(f"FAILED to build payload for block {n} after 3 attempts: {e}")
                    return (n, False, None)

    def run_multiproc(self, start, end, num_proc):
        print(f"PayloadBuilder starting: blocks {start} to {end} (total: {end - start + 1})")
        print(f"Using {num_proc} processes for building")

        # Create a worker-safe version without shared_state for multiprocessing
        worker_builder = PayloadBuilder(
            self.payload_dir,
            self.l1_rpc_urls,
            self.l2_rpc_urls,
            self.canyon_time,
            self.ecotone_time,
            self.isthmus_time,
            self.logging,
            shared_state=None  # No shared state for workers
        )

        p = Pool(num_proc)
        pbar = tqdm(p.imap_unordered(worker_builder.job, range(start, end + 1)), total=end - start + 1, file=io.StringIO() if self.logging else sys.stdout)
        logged_at = 0
        result_count = 0
        start_time = time.time()
        first_result_time = None
        
        failed_blocks = []
        for result in pbar:
            # Update shared state in main thread
            if result is not None:
                block_num, success, _ = result
                if self.shared_state is not None:
                    if success:
                        if first_result_time is None:
                            first_result_time = time.time()
                            print(f"First block completed after {first_result_time - start_time:.2f} seconds")
                        self.shared_state.mark_built(block_num)
                        result_count += 1
                        # Debug output for first few blocks and every 100 blocks
                        if block_num <= start + 10 or result_count % 100 == 0:
                            stats = self.shared_state.get_stats()
                            print(f"Built block {block_num} (total built: {stats['built']})")
                    else:
                        # Track failed blocks but don't stop the entire process
                        failed_blocks.append(block_num)
                        print(f"⚠ Block {block_num} failed to build, will be skipped")

            now = time.time()
            if self.logging and now > logged_at + 10:
                data = pbar.format_dict
                print(f'building payload | {data["n"]}/{data["total"]} | elapsed: {time.strftime("%H:%M:%S", time.gmtime(data["elapsed"]))}')
                logged_at = now

        p.close()
        p.join()

        total_blocks = end - start + 1
        successful_blocks = total_blocks - len(failed_blocks)
        print(f"PayloadBuilder completed: {successful_blocks}/{total_blocks} blocks built successfully")

        if failed_blocks:
            print(f"⚠ {len(failed_blocks)} blocks failed to build and will be skipped:")
            # Show first 10 failed blocks
            if len(failed_blocks) <= 10:
                print(f"  Failed blocks: {failed_blocks}")
            else:
                print(f"  First 10 failed blocks: {failed_blocks[:10]}")
                print(f"  ... and {len(failed_blocks) - 10} more")

        # Mark building as complete
        if self.shared_state is not None:
            self.shared_state.mark_building_complete()
