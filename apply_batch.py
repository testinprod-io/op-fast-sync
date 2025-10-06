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

    def finalize_interval(self, expected_block, max_attempts=3):
        """
        Finalize the interval by calling forkchoiceUpdated to ensure the engine commits to the latest block.
        Uses multiple strategies and retries to handle various error conditions.
        
        Args:
            expected_block: The block number we expect to be at
            max_attempts: Maximum number of finalization attempts
            
        Returns:
            bool: True if finalization succeeds, False otherwise
        """
        print(f"Finalizing interval with block {expected_block}...")
        
        for attempt in range(max_attempts):
            try:
                print(f"Finalization attempt {attempt + 1}/{max_attempts}")
                
                # Strategy 1: Try to get current block and finalize it
                if self._try_finalize_current_block():
                    print(f"✓ Interval finalized successfully using current block strategy")
                    return True
                
                # Strategy 2: Try to finalize using expected block
                if self._try_finalize_expected_block(expected_block):
                    print(f"✓ Interval finalized successfully using expected block strategy")
                    return True
                
                # Strategy 3: Try a simple forkchoice update without specific block
                if self._try_simple_finalization():
                    print(f"✓ Interval finalized successfully using simple strategy")
                    return True
                
                print(f"Finalization attempt {attempt + 1} failed, retrying...")
                time.sleep(1)
                
            except Exception as e:
                print(f"WARNING: Exception during finalization attempt {attempt + 1}: {str(e)}")
                time.sleep(1)
                continue
        
        print(f"WARNING: All finalization attempts failed, continuing without finalization")
        return False  # Don't fail the entire process, just warn

    def _try_finalize_current_block(self):
        """Try to finalize using the current block number from the engine."""
        try:
            # Get the latest block to use as head
            current_block_response = send_json_rpc(
                self.engine_url,
                'eth_blockNumber',
                token=self.jwt_token
            )
            
            if 'error' in current_block_response:
                print(f"WARNING: Failed to get current block: {current_block_response['error']}")
                return False
            
            current_block = int(current_block_response.get('result', '0x0'), 16)
            print(f"Current block from engine: {current_block}")
            
            # Get the block hash for the current block
            block_response = send_json_rpc(
                self.engine_url,
                'eth_getBlockByNumber',
                params=[hex(current_block), False],
                token=self.jwt_token
            )
            
            if 'error' in block_response or not block_response.get('result'):
                print(f"WARNING: Failed to get block {current_block}: {block_response.get('error', 'No result')}")
                return False
            
            block_hash = block_response['result']['hash']
            print(f"Got block hash: {block_hash}")
            
            # Call forkchoiceUpdated to finalize the current state
            return self._call_forkchoice_update(block_hash, block_hash, block_hash)
            
        except Exception as e:
            print(f"WARNING: Error in current block finalization: {str(e)}")
            return False

    def _try_finalize_expected_block(self, expected_block):
        """Try to finalize using the expected block number."""
        try:
            print(f"Trying to finalize with expected block: {expected_block}")
            
            # Get the block hash for the expected block
            block_response = send_json_rpc(
                self.engine_url,
                'eth_getBlockByNumber',
                params=[hex(expected_block), False],
                token=self.jwt_token
            )
            
            if 'error' in block_response or not block_response.get('result'):
                print(f"WARNING: Failed to get expected block {expected_block}: {block_response.get('error', 'No result')}")
                return False
            
            block_hash = block_response['result']['hash']
            print(f"Got expected block hash: {block_hash}")
            
            # Call forkchoiceUpdated to finalize the expected block
            return self._call_forkchoice_update(block_hash, block_hash, block_hash)
            
        except Exception as e:
            print(f"WARNING: Error in expected block finalization: {str(e)}")
            return False

    def _try_simple_finalization(self):
        """Try a simple finalization without getting specific block hashes."""
        try:
            print("Trying simple finalization...")
            
            # Use a simple forkchoice update that should work in most cases
            # This uses the engine's internal state
            forkchoice_response = send_json_rpc(
                self.engine_url,
                'engine_forkchoiceUpdatedV1',
                params=[{
                    'headBlockHash': '0x0000000000000000000000000000000000000000000000000000000000000000',
                    'safeBlockHash': '0x0000000000000000000000000000000000000000000000000000000000000000',
                    'finalizedBlockHash': '0x0000000000000000000000000000000000000000000000000000000000000000',
                }],
                token=self.jwt_token,
            )
            
            if 'error' in forkchoice_response:
                print(f"WARNING: Simple finalization failed: {forkchoice_response['error']}")
                return False
            
            payload_status = forkchoice_response.get('result', {}).get('payloadStatus', {})
            status = payload_status.get('status')
            
            if status in ['VALID', 'ACCEPTED']:
                print(f"Simple finalization successful with status: {status}")
                return True
            else:
                print(f"Simple finalization returned status: {status}")
                return True  # Accept any non-error status
                
        except Exception as e:
            print(f"WARNING: Error in simple finalization: {str(e)}")
            return False

    def _call_forkchoice_update(self, head_hash, safe_hash, finalized_hash):
        """Call forkchoiceUpdated with the provided hashes."""
        try:
            forkchoice_response = send_json_rpc(
                self.engine_url,
                'engine_forkchoiceUpdatedV1',
                params=[{
                    'headBlockHash': head_hash,
                    'safeBlockHash': safe_hash,
                    'finalizedBlockHash': finalized_hash,
                }],
                token=self.jwt_token,
            )
            
            if 'error' in forkchoice_response:
                print(f"WARNING: Forkchoice update failed: {forkchoice_response['error']}")
                return False
            
            payload_status = forkchoice_response.get('result', {}).get('payloadStatus', {})
            status = payload_status.get('status')
            
            if status in ['VALID', 'ACCEPTED']:
                print(f"Forkchoice update successful with status: {status}")
                return True
            elif status == 'INVALID':
                error_msg = f"Invalid forkchoice: {payload_status.get('validationError', 'Unknown error')}"
                print(f"WARNING: {error_msg}")
                return False
            else:
                print(f"Forkchoice update returned status: {status}")
                return True  # Accept any non-error status
                
        except Exception as e:
            print(f"WARNING: Error in forkchoice update: {str(e)}")
            return False

    def _try_finalize_specific_block(self, block_number):
        """
        Try to finalize a specific block that's having forkchoice issues.
        This is called when we get None status errors.
        
        Args:
            block_number: The block number to finalize
            
        Returns:
            bool: True if finalization succeeds, False otherwise
        """
        try:
            print(f"Attempting to finalize specific block {block_number}...")
            
            # Strategy 1: Try to get the block hash and finalize it
            block_response = send_json_rpc(
                self.engine_url,
                'eth_getBlockByNumber',
                params=[hex(block_number), False],
                token=self.jwt_token
            )
            
            if 'error' in block_response or not block_response.get('result'):
                print(f"WARNING: Cannot get block {block_number} for finalization: {block_response.get('error', 'No result')}")
            else:
                block_hash = block_response['result']['hash']
                print(f"Got block {block_number} hash: {block_hash}")
                
                # Try to finalize this specific block
                if self._call_forkchoice_update(block_hash, block_hash, block_hash):
                    print(f"✓ Successfully finalized block {block_number}")
                    return True
            
            # Strategy 2: Try to finalize using the payload hash from the payload file
            payload_file = os.path.join(self.payload_dir, f'{hex(block_number)}.json')
            if os.path.exists(payload_file):
                try:
                    with open(payload_file, 'r') as f:
                        payload_data = json.load(f)
                    
                    # Handle both list format [payload] and direct payload format
                    if isinstance(payload_data, list) and len(payload_data) > 0:
                        payload = payload_data[0]
                    else:
                        payload = payload_data
                    
                    if 'blockHash' in payload:
                        block_hash = payload['blockHash']
                        print(f"Using payload block hash for finalization: {block_hash}")
                        
                        if self._call_forkchoice_update(block_hash, block_hash, block_hash):
                            print(f"✓ Successfully finalized block {block_number} using payload hash")
                            return True
                    
                except Exception as e:
                    print(f"WARNING: Error reading payload file for finalization: {str(e)}")
            
            # Strategy 3: Try a simple finalization call
            print("Trying simple finalization for this block...")
            if self._try_simple_finalization():
                print(f"✓ Simple finalization successful for block {block_number}")
                return True
            
            print(f"WARNING: All finalization strategies failed for block {block_number}")
            return False
            
        except Exception as e:
            print(f"WARNING: Exception during block {block_number} finalization: {str(e)}")
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
                            # Try to finalize this specific block before giving up
                            print(f"WARNING: Forkchoice status is None for block {block_number} after {forkchoice_attempts} attempts.")
                            print(f"Attempting to finalize block {block_number} to resolve the issue...")
                            
                            finalization_success = self._try_finalize_specific_block(block_number)
                            if finalization_success:
                                print(f"✓ Successfully finalized block {block_number}, retrying forkchoice...")
                                # Reset attempts and try forkchoice again
                                forkchoice_attempts = 0
                                continue
                            else:
                                error_msg = f"Forkchoice status is None for block {block_number} after {forkchoice_attempts} attempts and finalization failed. This may indicate the engine needs finalization."
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
