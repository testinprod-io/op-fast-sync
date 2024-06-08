import os

from apply_batch import PayloadApplier
from build_payloads import PayloadBuilder
from utils import parse_args, send_json_rpc, RPCMethod

if __name__ == '__main__':
    args = parse_args()
    if not os.path.exists(args.payload_dir):
        os.makedirs(args.payload_dir)
        print(f'Created payload dir: {args.payload_dir}')
    engine_header = send_json_rpc(args.rpc_url, RPCMethod.GetBlockByNumber, params=['latest', False])
    start = int(engine_header['number'], 16) + 1

    unsafe_header = send_json_rpc(args.l2_rpc_urls[0], RPCMethod.GetBlockByNumber, params=['latest', False])
    end = int(unsafe_header['number'], 16)

    safe_header = send_json_rpc(args.l2_rpc_urls[0], RPCMethod.GetBlockByNumber, params=['safe', False])
    safe_number = int(safe_header['number'], 16)
    safe_hash = safe_header['hash']

    finalized_header = send_json_rpc(args.l2_rpc_urls[0], RPCMethod.GetBlockByNumber, params=['finalized', False])
    finalized_number = int(finalized_header['number'], 16)
    finalized_hash = finalized_header['hash']

    print(f'Current execution engine header: {start - 1}')
    print(f'Target unsafe block: {end}')
    print(f'Target safe block: {safe_number}')
    print(f'Target finalized block: {finalized_number}')

    payload_builder = PayloadBuilder(args.payload_dir, args.l1_rpc_urls, args.l2_rpc_urls, args.canyon_time, args.ecotone_time, args.logging)
    payload_applier = PayloadApplier(
        args.engine_url,
        args.jwt_secret,
        args.payload_dir,
        start,
        end,
        args.batch_size,
        safe_number,
        safe_hash,
        finalized_number,
        finalized_hash,
        args.canyon_time,
        args.ecotone_time,
        args.logging
    )

    print('Start building payloads')
    payload_builder.run_multiproc(start, end, args.num_proc)

    print('Start applying payloads')
    payload_applier.run()
