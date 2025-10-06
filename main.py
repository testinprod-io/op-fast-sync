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
    rpc_end = int(unsafe_header['number'], 16)
    
    # Use block_end flag if provided, otherwise use latest block from RPC
    end = args.block_end if args.block_end is not None else rpc_end
    
    # Validate that block_end is not less than start
    if args.block_end is not None and args.block_end < start:
        print(f'Error: --block-end ({args.block_end}) cannot be less than start block ({start})')
        exit(1)
    
    # Warn if block_end is greater than latest block from RPC
    if args.block_end is not None and args.block_end > rpc_end:
        print(f'Warning: --block-end ({args.block_end}) is greater than latest block from RPC ({rpc_end})')

    safe_header = send_json_rpc(args.l2_rpc_urls[0], RPCMethod.GetBlockByNumber, params=['safe', False])
    safe_number = int(safe_header['number'], 16)
    safe_hash = safe_header['hash']

    finalized_header = send_json_rpc(args.l2_rpc_urls[0], RPCMethod.GetBlockByNumber, params=['finalized', False])
    finalized_number = int(finalized_header['number'], 16)
    finalized_hash = finalized_header['hash']

    print(f'Current execution engine header: {start - 1}')
    if args.block_end is not None:
        print(f'Target end block (user specified): {end}')
        print(f'Latest block from RPC: {rpc_end}')
    else:
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
