import io
import json
import os
import sys
import time

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
            isthmus_time,
            logging=False,
            shared_state=None,
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
        self.isthmus_time = isthmus_time
        self.logging = logging
        self.shared_state = shared_state

    def _get_jwt_token(self):
        auth_payload = {
            'iat': int(time.time())
        }
        self.jwt_token = jwt.encode(
            auth_payload,
            bytes.fromhex(self.jwt_secret[2:] if self.jwt_secret.startswith('0x') else self.jwt_secret)
        )

    def apply(self, block_number):
        payload_file = os.path.join(self.payload_dir, f'{hex(block_number)}.json')
        if not os.path.exists(payload_file):
            raise FileNotFoundError(f"Payload file not found: {payload_file}")
        
        with open(payload_file, 'r') as f:
            payload_array = json.load(f)

        # The payload is stored as an array, extract the actual payload (first element)
        payload = payload_array[0]
        timestamp = int(payload['timestamp'], 16)
        payload_version = 4 if timestamp >= self.isthmus_time else 3 if timestamp >= self.ecotone_time else 2 if timestamp >= self.canyon_time else 1
        # forkchoiceUpdated stays at V3 for Isthmus (V4 is only for newPayload/getPayload)
        fcu_version = 3 if timestamp >= self.ecotone_time else 2 if timestamp >= self.canyon_time else 1
        send_json_rpc(self.engine_url, f'engine_newPayloadV{payload_version}', params=payload_array, token=self.jwt_token, timeout=60)

        if block_number < self.end and block_number % self.batch_size < self.batch_size - 1:
            return

        # Retry loop for forkchoiceUpdated with exponential backoff
        max_fcu_attempts = 20
        fcu_attempt = 0
        backoff_time = 0.5

        while fcu_attempt < max_fcu_attempts:
            fcu_attempt += 1
            try:
                res = send_json_rpc(
                    self.engine_url,
                    f'engine_forkchoiceUpdatedV{fcu_version}',
                    params=[
                        {
                            'headBlockHash': payload['blockHash'],
                            'safeBlockHash': payload['blockHash'] if block_number < self.target_safe_number else self.target_safe_hash,
                            'finalizedBlockHash': payload['blockHash'] if block_number < self.target_finalized_number else self.target_finalized_hash,
                        },
                    ],
                    token=self.jwt_token,
                    timeout=120,  # Increased from 60s to 120s
                )

                # Check status
                if res['payloadStatus']['status'] == 'SYNCING':
                    if fcu_attempt % 10 == 0:
                        print(f"  Block {block_number}: Still syncing after {fcu_attempt} attempts, waiting...")
                    time.sleep(backoff_time)
                    backoff_time = min(backoff_time * 1.5, 5.0)  # Exponential backoff, max 5s
                    continue

                # Success
                break

            except Exception as e:
                error_msg = str(e)

                # Handle "execution service is busy" errors
                if "busy" in error_msg.lower() or "timeout" in error_msg.lower():
                    if fcu_attempt % 5 == 0:
                        print(f"  Block {block_number}: Engine busy (attempt {fcu_attempt}/{max_fcu_attempts}), waiting {backoff_time:.1f}s...")
                    time.sleep(backoff_time)
                    backoff_time = min(backoff_time * 1.5, 10.0)  # Exponential backoff, max 10s
                    continue
                else:
                    # Other errors, re-raise
                    raise

        # Check if we exhausted retries
        if fcu_attempt >= max_fcu_attempts:
            raise Exception(f"forkchoiceUpdated failed after {max_fcu_attempts} attempts for block {block_number}")

    def job(self, block_number):
        max_attempts = 10  # Increased from 3 to 10
        for attempt in range(max_attempts):
            try:
                self.apply(block_number)
                return
            except Exception as e:
                error_msg = str(e)
                # Only print every other attempt to reduce spam
                if attempt % 2 == 0 or attempt == max_attempts - 1:
                    print(f"Error applying block {block_number} (attempt {attempt + 1}/{max_attempts}): {e}")

                # For "busy" errors, wait longer before retrying
                if "busy" in error_msg.lower():
                    wait_time = min(2.0 * (attempt + 1), 20.0)  # Up to 20s wait
                    if attempt % 2 == 0:
                        print(f"  Waiting {wait_time:.1f}s before retry...")
                    time.sleep(wait_time)

                self._get_jwt_token()

        print(f"Failed to apply block {block_number} after {max_attempts} attempts")
        exit()

    def run(self):
        print(f"PayloadApplier starting: blocks {self.start} to {self.end} (total: {self.end - self.start + 1})")
        self._get_jwt_token()
        print(f"JWT token generated successfully")
        
        if self.shared_state is None:
            # Fallback to sequential mode if no shared state
            pbar = tqdm(range(self.start, self.end + 1), total=self.end - self.start + 1, file=io.StringIO() if self.logging else sys.stdout)
            logged_at = 0
            for block_number in pbar:
                if block_number == self.start:
                    print(f"Starting to apply first block: {block_number}")
                self.job(block_number)
                now = time.time()
                if self.logging and now > logged_at + 10:
                    data = pbar.format_dict
                    print(f'applying payload | {data["n"]}/{data["total"]} | elapsed: {time.strftime("%H:%M:%S", time.gmtime(data["elapsed"]))}')
                    logged_at = now
            return

        # Concurrent mode with shared state
        pbar = tqdm(range(self.start, self.end + 1), total=self.end - self.start + 1, file=io.StringIO() if self.logging else sys.stdout)
        logged_at = 0
        wait_count = 0
        
        for block_number in pbar:
            if block_number == self.start:
                print(f"Starting to apply first block: {block_number}")

            # Wait for blocks to be available
            block_is_available = False
            while True:
                stats = self.shared_state.get_stats()

                # Check if the current block is available
                if self.shared_state.is_block_built(block_number):
                    block_is_available = True
                    break

                # If building is complete and this block isn't built, skip it
                if stats['building_complete']:
                    if not self.shared_state.is_block_built(block_number):
                        print(f"⚠ Block {block_number} not built (failed during building), skipping")
                        block_is_available = False
                        break

                # Debug output
                wait_count += 1
                if block_number == self.start and wait_count % 5 == 1:  # Every 5th wait attempt
                    print(f"Waiting for block {block_number} to be built... (built: {stats['built']}/{stats['total']}, wait attempt: {wait_count})")

                # Wait for the specific block to be available
                if not self.shared_state.wait_for_blocks(block_number - 1, 1, timeout=2.0):
                    # Timeout, check again
                    continue

            # Only apply if the block was successfully built
            if block_is_available:
                self.job(block_number)
            else:
                # Skip this block and continue to next
                pbar.update(1)
            now = time.time()
            if self.logging and now > logged_at + 10:
                data = pbar.format_dict
                print(f'applying payload | {data["n"]}/{data["total"]} | elapsed: {time.strftime("%H:%M:%S", time.gmtime(data["elapsed"]))}')
                logged_at = now
