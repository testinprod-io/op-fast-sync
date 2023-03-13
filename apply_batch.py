import json
import os
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

    def _get_jwt_token(self):
        auth_payload = {
            'iat': int(time.time())
        }
        self.jwt_token = jwt.encode(
            auth_payload,
            bytes.fromhex(self.jwt_secret[2:] if self.jwt_secret.startswith('0x') else self.jwt_secret)
        )

    def apply(self, block_number):
        with open(os.path.join(self.payload_dir, f'{hex(block_number)}.json'), 'r') as f:
            payload = json.load(f)
        send_json_rpc(self.engine_url, 'engine_newPayloadV1', params=[payload], token=self.jwt_token)

        if block_number < self.end and block_number % self.batch_size < self.batch_size - 1:
            return

        while True:
            res = send_json_rpc(
                self.engine_url,
                'engine_forkchoiceUpdatedV1',
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
        for _ in range(3):
            try:
                self.apply(block_number)
                return
            except Exception as e:
                self._get_jwt_token()
        exit()

    def run(self):
        self._get_jwt_token()
        for block_number in tqdm(range(self.start, self.end + 1), total=self.end - self.start + 1):
            self.job(block_number)
