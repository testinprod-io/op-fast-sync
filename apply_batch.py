import io
import json
import os
import sys
import time
import traceback
from datetime import datetime

import jwt
from tqdm import tqdm

from utils import send_json_rpc


class PayloadApplier:
    def __init__(
            self,
            engine_url,
            jwt_secret_path,
            payload_dir,
            start,
            end,
            batch_size,
            target_safe_number,
            target_safe_hash,
            target_finalized_number,
            target_finalized_hash,
            canyon_time,
            ecotone_time,
            logging=False,
            error_log_file=None,
    ):
        self.engine_url = engine_url
        with open(jwt_secret_path, 'r') as f:
            self.jwt_secret = f.readline().strip()
        self.payload_dir = payload_dir
        self.start = start
        self.end = end
        self.batch_size = batch_size
        self.target_safe_number = target_safe_number
        self.target_safe_hash = target_safe_hash
        self.target_finalized_number = target_finalized_number
        self.target_finalized_hash = target_finalized_hash
        self.canyon_time = canyon_time
        self.ecotone_time = ecotone_time
        self.logging = logging

    def _get_jwt_token(self):
        auth_payload = {
            'iat': int(time.time())
        }
        self.jwt_token = jwt.encode(
            auth_payload,
            bytes.fromhex(self.jwt_secret[2:] if self.jwt_secret.startswith('0x') else self.jwt_secret)
        )

    def finalize_interval(self, expected_block):
        """
        Finalize the interval by calling forkchoiceUpdated to ensure the engine commits to the latest block.
        
        Args:
            expected_block: The block number we expect to be at
            
        Returns:
            bool: True if finalization succeeds, False otherwise
        """
        try:
            print(f"Finalizing interval with block {expected_block}...")
            
            # Get the latest block to use as head
            current_block_response = send_json_rpc(
                self.engine_url,
                'eth_blockNumber',
                token=self.jwt_token
            )
            
            if 'error' in current_block_response:
                print(f"ERROR: Failed to get current block for finalization: {current_block_response['error']}")
                return False
            
            current_block = int(current_block_response.get('result', '0x0'), 16)
            
            # Get the block hash for the current block
            block_response = send_json_rpc(
                self.engine_url,
                'eth_getBlockByNumber',
                params=[hex(current_block), False],
                token=self.jwt_token
            )
            
            if 'error' in block_response or not block_response.get('result'):
                print(f"ERROR: Failed to get block {current_block} for finalization: {block_response.get('error', 'No result')}")
                return False
            
            block_hash = block_response['result']['hash']
            
            # Call forkchoiceUpdated to finalize the current state
            forkchoice_response = send_json_rpc(
                self.engine_url,
                'engine_forkchoiceUpdatedV1',
                params=[{
                    'headBlockHash': block_hash,
                    'safeBlockHash': block_hash,
                    'finalizedBlockHash': block_hash,
                }],
                token=self.jwt_token,
            )
            
            if 'error' in forkchoice_response:
                print(f"ERROR: Forkchoice finalization failed: {forkchoice_response['error']}")
                return False
            
            payload_status = forkchoice_response.get('result', {}).get('payloadStatus', {})
            status = payload_status.get('status')
            
            if status in ['VALID', 'ACCEPTED']:
                print(f"✓ Interval finalized successfully with status: {status}")
                return True
            elif status == 'INVALID':
                error_msg = f"Invalid forkchoice during finalization: {payload_status.get('validationError', 'Unknown error')}"
                print(f"ERROR: {error_msg}")
                return False
            else:
                print(f"WARNING: Unexpected forkchoice status during finalization: {status}")
                return True  # Continue anyway, might still be valid
                
        except Exception as e:
            print(f"ERROR: Exception during interval finalization: {str(e)}")
            return False

    def verify_block_number(self, expected_block, max_attempts=30, delay=2):
        """
        Verify that the engine has reached the expected block number.
        
        Args:
            expected_block: The block number we expect to be at
            max_attempts: Maximum number of verification attempts
            delay: Delay between attempts in seconds
            
        Returns:
            bool: True if verification succeeds, False otherwise
        """
        print(f"Verifying engine has reached block {expected_block}...")
        
        # First, try to finalize the current state
        if not self.finalize_interval(expected_block):
            print(f"WARNING: Interval finalization failed, continuing with verification...")
        
        for attempt in range(max_attempts):
            try:
                # Get current block number from engine
                current_block_response = send_json_rpc(
                    self.engine_url,
                    'eth_blockNumber',
                    token=self.jwt_token
                )
                
                if 'error' in current_block_response:
                    print(f"WARNING: Error getting block number (attempt {attempt + 1}/{max_attempts}): {current_block_response['error']}")
                    time.sleep(delay)
                    continue
                
                current_block = int(current_block_response.get('result', '0x0'), 16)
                expected_hex = hex(expected_block)
                
                print(f"Attempt {attempt + 1}/{max_attempts}: Current block: {current_block} (0x{current_block:x}), Expected: {expected_block} (0x{expected_block:x})")
                
                if current_block >= expected_block:
                    print(f"✓ Verification successful: Engine has reached block {current_block} >= {expected_block}")
                    return True
                
                # If we're close but not quite there, wait a bit longer
                if current_block >= expected_block - 5:
                    print(f"Engine is close (block {current_block}), waiting for final blocks...")
                    time.sleep(delay)
                    continue
                    
                # If we're far behind, something might be wrong
                if attempt >= 5 and current_block < expected_block - 10:
                    print(f"WARNING: Engine seems to be stuck at block {current_block}, expected {expected_block}")
                    
                time.sleep(delay)
                
            except Exception as e:
                print(f"WARNING: Error during verification (attempt {attempt + 1}/{max_attempts}): {str(e)}")
                time.sleep(delay)
                continue
        
        print(f"✗ Verification failed: Engine did not reach block {expected_block} after {max_attempts} attempts")
        return False

    def apply(self, block_number):
        try:
            # Load payload file
            payload_file = os.path.join(self.payload_dir, f'{hex(block_number)}.json')
            if not os.path.exists(payload_file):
                error_msg = f"Payload file not found: {payload_file}"
                print(f"ERROR: {error_msg}")
                raise FileNotFoundError(error_msg)
            
            with open(payload_file, 'r') as f:
                payload_data = json.load(f)

            # Handle both list format [payload] and direct payload format
            if isinstance(payload_data, list):
                if len(payload_data) == 0:
                    error_msg = f"Empty payload array for block {block_number}"
                    print(f"ERROR: {error_msg}")
                    raise Exception(error_msg)
                payload = payload_data[0]
            else:
                payload = payload_data

            timestamp = int(payload['timestamp'], 16)
            version = 3 if timestamp >= self.ecotone_time else 2 if timestamp >= self.canyon_time else 1
            
            # Send newPayload request
            try:
                # Use the original payload_data for the API call to maintain correct format
                new_payload_response = send_json_rpc(
                    self.engine_url, 
                    f'engine_newPayloadV{version}', 
                    params=payload_data, 
                    token=self.jwt_token
                )
                
                # Check for errors in newPayload response
                if 'error' in new_payload_response:
                    error_msg = f"newPayload error for block {block_number}: {new_payload_response['error']}"
                    print(f"ERROR: {error_msg}")
                    raise Exception(error_msg)
                    
                payload_status = new_payload_response.get('result', {})
                if payload_status.get('status') == 'INVALID':
                    error_msg = f"Invalid payload for block {block_number}: {payload_status.get('validationError', 'Unknown error')}"
                    print(f"ERROR: {error_msg}")
                    raise Exception(error_msg)
                    
            except Exception as e:
                error_msg = f"Failed to send newPayload for block {block_number}: {str(e)}"
                print(f"ERROR: {error_msg}")
                raise

            # Skip forkchoice update if not at batch boundary
            if block_number < self.end and block_number % self.batch_size < self.batch_size - 1:
                return

            # Send forkchoice update
            forkchoice_attempts = 0
            max_forkchoice_attempts = 100  # Prevent infinite loops
            
            while forkchoice_attempts < max_forkchoice_attempts:
                try:
                    forkchoice_response = send_json_rpc(
                        self.engine_url,
                        f'engine_forkchoiceUpdatedV{version}',
                        params=[
                            {
                                'headBlockHash': payload['blockHash'],
                                'safeBlockHash': payload['blockHash'] if block_number < self.target_safe_number else self.target_safe_hash,
                                'finalizedBlockHash': payload['blockHash'] if block_number < self.target_finalized_number else self.target_finalized_hash,
                            },
                        ],
                        token=self.jwt_token,
                    )
                    
                    # Check for errors in forkchoice response
                    if 'error' in forkchoice_response:
                        error_msg = f"forkchoiceUpdated error for block {block_number}: {forkchoice_response['error']}"
                        print(f"ERROR: {error_msg}")
                        raise Exception(error_msg)
                    
                    payload_status = forkchoice_response.get('result', {}).get('payloadStatus', {})
                    status = payload_status.get('status')
                    
                    if status == 'SYNCING':
                        forkchoice_attempts += 1
                        time.sleep(0.1)
                        continue
                    elif status == 'INVALID':
                        error_msg = f"Invalid forkchoice for block {block_number}: {payload_status.get('validationError', 'Unknown error')}"
                        print(f"ERROR: {error_msg}")
                        raise Exception(error_msg)
                    elif status == 'VALID':
                        break
                    elif status is None:
                        # Status is None, this often means the engine needs more time or a finalizing call
                        if forkchoice_attempts < 10:  # Give more attempts for None status
                            forkchoice_attempts += 1
                            print(f"WARNING: Forkchoice status is None for block {block_number} (attempt {forkchoice_attempts}/100), retrying...")
                            time.sleep(0.5)  # Wait a bit longer for None status
                            continue
                        else:
                            error_msg = f"Forkchoice status is None for block {block_number} after {forkchoice_attempts} attempts. This may indicate the engine needs finalization."
                            print(f"ERROR: {error_msg}")
                            raise Exception(error_msg)
                    else:
                        error_msg = f"Unknown forkchoice status for block {block_number}: {status} (type: {type(status)})"
                        print(f"ERROR: {error_msg}")
                        raise Exception(error_msg)
                        
                except Exception as e:
                    error_msg = f"Failed to send forkchoiceUpdated for block {block_number} (attempt {forkchoice_attempts + 1}): {str(e)}"
                    print(f"ERROR: {error_msg}")
                    raise
            
            if forkchoice_attempts >= max_forkchoice_attempts:
                error_msg = f"Max forkchoice attempts reached for block {block_number}"
                print(f"ERROR: {error_msg}")
                raise Exception(error_msg)
                
        except Exception as e:
            # Log detailed error information to stdout
            error_details = {
                'block_number': block_number,
                'timestamp': datetime.now().isoformat(),
                'error_type': type(e).__name__,
                'error_message': str(e),
                'traceback': traceback.format_exc(),
                'payload_file': os.path.join(self.payload_dir, f'{hex(block_number)}.json'),
                'engine_url': self.engine_url,
                'payload_exists': os.path.exists(os.path.join(self.payload_dir, f'{hex(block_number)}.json'))
            }
            
            print(f"ERROR: Apply failed for block {block_number}:")
            print(json.dumps(error_details, indent=2))
            raise

    def job(self, block_number):
        max_retries = 3
        retry_delay = 1  # seconds
        
        for attempt in range(max_retries):
            try:
                self.apply(block_number)
                if attempt > 0:
                    print(f"SUCCESS: Block {block_number} succeeded on attempt {attempt + 1}")
                return
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"WARNING: Block {block_number} failed on attempt {attempt + 1}/{max_retries}: {str(e)}. Retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                    # Refresh JWT token for retry
                    try:
                        self._get_jwt_token()
                    except Exception as jwt_error:
                        print(f"ERROR: Failed to refresh JWT token for block {block_number}: {str(jwt_error)}")
                else:
                    # Final attempt failed
                    print(f"ERROR: Block {block_number} failed after {max_retries} attempts. Final error: {str(e)}")
                    
        # If we get here, all retries failed
        error_msg = f"CRITICAL: Block {block_number} failed after {max_retries} attempts. Exiting."
        print(f"\n{error_msg}")
        sys.exit(1)

    def run(self):
        self._get_jwt_token()
        pbar = tqdm(range(self.start, self.end + 1), total=self.end - self.start + 1, file=io.StringIO() if self.logging else sys.stdout)
        logged_at = 0
        for block_number in pbar:
            self.job(block_number)
            now = time.time()
            if self.logging and now > logged_at + 10:
                data = pbar.format_dict
                print(f'applying payload | {data["n"]}/{data["total"]} | elapsed: {time.strftime("%H:%M:%S", time.gmtime(data["elapsed"]))}')
                logged_at = now

    def run_interval(self, interval_start, interval_end):
        """Run payload application for a specific interval of blocks"""
        self._get_jwt_token()
        total_blocks = interval_end - interval_start + 1
        pbar = tqdm(range(interval_start, interval_end + 1), total=total_blocks, file=io.StringIO() if self.logging else sys.stdout)
        logged_at = 0
        for block_number in pbar:
            self.job(block_number)
            now = time.time()
            if self.logging and now > logged_at + 10:
                data = pbar.format_dict
                print(f'applying payload | {data["n"]}/{data["total"]} | elapsed: {time.strftime("%H:%M:%S", time.gmtime(data["elapsed"]))}')
                logged_at = now
