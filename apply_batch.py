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
            logging=False,
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

    def apply(self, block_number):
        payload_file = os.path.join(self.payload_dir, f'{hex(block_number)}.json')
        if not os.path.exists(payload_file):
            raise FileNotFoundError(f"Payload file not found: {payload_file}")
        
        with open(payload_file, 'r') as f:
            payload_array = json.load(f)

        # The payload is stored as an array, extract the actual payload (first element)
        payload = payload_array[0]
        timestamp = int(payload['timestamp'], 16)
        version = 3 if timestamp >= self.ecotone_time else 2 if timestamp >= self.canyon_time else 1
        send_json_rpc(self.engine_url, f'engine_newPayloadV{version}', params=payload_array, token=self.jwt_token)

        if block_number < self.end and block_number % self.batch_size < self.batch_size - 1:
            return

        while True:
            res = send_json_rpc(
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
            if res['payloadStatus']['status'] == 'SYNCING':
                time.sleep(0.1)
                continue
            break

    def job(self, block_number):
        for attempt in range(3):
            try:
                self.apply(block_number)
                return
            except Exception as e:
                print(f"Error applying block {block_number} (attempt {attempt + 1}/3): {e}")
                self._get_jwt_token()
        print(f"Failed to apply block {block_number} after 3 attempts")
        exit()

    def run(self):
        print(f"PayloadApplier starting: blocks {self.start} to {self.end} (total: {self.end - self.start + 1})")
        self._get_jwt_token()
        print(f"JWT token generated successfully")
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
