import io
import json
import os
import pprint
import random
import sys
import time
import traceback
from datetime import datetime
from multiprocessing import Pool

import rlp
import eth_abi
from tqdm import tqdm

from utils import send_json_rpc, RPCMethod, L1_BLOCK_CONTRACT_ADDR

pp = pprint.PrettyPrinter(indent=2)
L1_INFO_TX_TYPES = ['uint64', 'uint64', 'uint256', 'bytes32', 'uint64', 'bytes32', 'uint256', 'uint256']

class PayloadBuilder:
    def __init__(self, payload_dir, l1_rpc_urls, l2_rpc_urls, canyon_time, ecotone_time, logging=False):
        self.payload_dir = payload_dir
        self.l1_rpc_urls = l1_rpc_urls
        self.l2_rpc_urls = l2_rpc_urls
        self.canyon_time = canyon_time
        self.ecotone_time = ecotone_time
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
        try:
            l2_block_number = hex(n)
            payload_file = os.path.join(self.payload_dir, f'{l2_block_number}.json')
            
            # Skip if payload already exists
            if os.path.exists(payload_file):
                return True

            l2_rpc_url = self._get_l2_rpc_url()

            # 1. Get block from L2
            try:
                l2_block = send_json_rpc(l2_rpc_url, RPCMethod.GetBlockByNumber, params=[l2_block_number, True])
                if not l2_block:
                    error_msg = f"L2 block {n} not found or empty response from {l2_rpc_url}"
                    print(f"ERROR: {error_msg}")
                    raise Exception(error_msg)
                    
                if not l2_block.get('transactions') or len(l2_block['transactions']) == 0:
                    error_msg = f"L2 block {n} has no transactions"
                    print(f"ERROR: {error_msg}")
                    raise Exception(error_msg)
                    
            except Exception as e:
                error_msg = f"Failed to get L2 block {n} from {l2_rpc_url}: {str(e)}"
                print(f"ERROR: {error_msg}")
                raise

            # 2. Get L1 block number from transaction input
            try:
                txInput = l2_block['transactions'][0]['input']
                if not txInput or len(txInput) < 10:
                    error_msg = f"Invalid transaction input for block {n}: {txInput}"
                    print(f"ERROR: {error_msg}")
                    raise Exception(error_msg)
                    
                if int(l2_block['timestamp'], 16) >= self.ecotone_time:
                    l1_block_number = hex(int.from_bytes(bytes.fromhex(txInput[2:])[28:36], 'big'))
                else:
                    l1_block_number = hex(eth_abi.decode(L1_INFO_TX_TYPES, bytes.fromhex(txInput[10:]))[0])
                    
            except Exception as e:
                error_msg = f"Failed to extract L1 block number for block {n}: {str(e)}"
                print(f"ERROR: {error_msg}")
                raise

            # 3. Get L1 mixhash
            l1_rpc_url = self._get_l1_rpc_url()
            try:
                l1_response = send_json_rpc(l1_rpc_url, RPCMethod.GetBlockByNumber, params=[l1_block_number, False])
                if not l1_response or not l1_response.get('mixHash'):
                    error_msg = f"L1 block {l1_block_number} not found or missing mixHash from {l1_rpc_url}"
                    print(f"ERROR: {error_msg}")
                    raise Exception(error_msg)
                prevRandao = l1_response['mixHash']
                
            except Exception as e:
                error_msg = f"Failed to get L1 mixhash for block {l1_block_number} from {l1_rpc_url}: {str(e)}"
                print(f"ERROR: {error_msg}")
                raise

            # 4. Encode transactions
            encoded_txs = []
            try:
                for i, tx in enumerate(l2_block['transactions']):
                    try:
                        tx_type = tx['type'][2:]
                        to = tx.get('to')
                        if to is None:
                            to = b''
                        else:
                            to = bytes.fromhex(to[2:])
                            
                        if tx_type == '1':
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
                        elif tx_type == '2':
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
                        elif tx_type == '7e':
                            encoded_tx = '0x' + (
                                bytes.fromhex(tx_type) +
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
                        
                    except Exception as e:
                        error_msg = f"Failed to encode transaction {i} in block {n}: {str(e)}"
                        print(f"ERROR: {error_msg}")
                        raise
                        
            except Exception as e:
                error_msg = f"Failed to encode transactions for block {n}: {str(e)}"
                print(f"ERROR: {error_msg}")
                raise

            # 5. Build payload
            try:
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

                # Write payload to file
                with open(payload_file, 'w') as f:
                    json.dump(payloadArray, f)
                    
            except Exception as e:
                error_msg = f"Failed to build payload for block {n}: {str(e)}"
                print(f"ERROR: {error_msg}")
                raise

            return True
            
        except Exception as e:
            # Log detailed error information to stdout
            error_details = {
                'block_number': n,
                'timestamp': datetime.now().isoformat(),
                'error_type': type(e).__name__,
                'error_message': str(e),
                'traceback': traceback.format_exc(),
                'payload_file': os.path.join(self.payload_dir, f'{hex(n)}.json'),
                'l1_rpc_urls': self.l1_rpc_urls,
                'l2_rpc_urls': self.l2_rpc_urls,
                'canyon_time': self.canyon_time,
                'ecotone_time': self.ecotone_time
            }
            
            print(f"ERROR: Build failed for block {n}:")
            print(json.dumps(error_details, indent=2))
            raise

    def job(self, n):
        max_retries = 3
        retry_delay = 1  # seconds
        
        for attempt in range(max_retries):
            try:
                result = self.build(n)
                if attempt > 0:
                    print(f"SUCCESS: Block {n} payload built on attempt {attempt + 1}")
                return result
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"WARNING: Block {n} payload build failed on attempt {attempt + 1}/{max_retries}: {str(e)}. Retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                else:
                    # Final attempt failed
                    print(f"ERROR: Block {n} payload build failed after {max_retries} attempts. Final error: {str(e)}")
                    
        # If we get here, all retries failed
        error_msg = f"CRITICAL: Block {n} payload build failed after {max_retries} attempts. Exiting."
        print(error_msg)
        raise Exception(error_msg)

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
