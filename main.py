import os
import sys

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

    # Use end_block if specified, otherwise get latest block
    if args.end_block is not None:
        end = args.end_block
        print(f'Using specified end block: {end}')
    else:
        unsafe_header = send_json_rpc(args.l2_rpc_urls[0], RPCMethod.GetBlockByNumber, params=['latest', False])
        end = int(unsafe_header['number'], 16)
        print(f'Using latest block as end: {end}')

    safe_header = send_json_rpc(args.l2_rpc_urls[0], RPCMethod.GetBlockByNumber, params=['safe', False])
    safe_number = int(safe_header['number'], 16)
    safe_hash = safe_header['hash']

    finalized_header = send_json_rpc(args.l2_rpc_urls[0], RPCMethod.GetBlockByNumber, params=['finalized', False])
    finalized_number = int(finalized_header['number'], 16)
    finalized_hash = finalized_header['hash']

    print(f'Current execution engine header: {start - 1}')
    print(f'Target end block: {end}')
    print(f'Target safe block: {safe_number}')
    print(f'Target finalized block: {finalized_number}')
    print(f'Sync interval: {args.interval} blocks')

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

    # Process blocks in intervals
    current_start = start
    interval_count = 0
    
    try:
        while current_start <= end:
            interval_end = min(current_start + args.interval - 1, end)
            interval_count += 1
            
            print(f'\n=== Processing interval {interval_count}: blocks {current_start} to {interval_end} ===')
            
            try:
                print(f'Building payloads for interval {interval_count}')
                payload_builder.run_multiproc(current_start, interval_end, args.num_proc)
                
                print(f'Applying payloads for interval {interval_count}')
                payload_applier.run_interval(current_start, interval_end)
                
                print(f'✓ Completed interval {interval_count}: blocks {current_start} to {interval_end}')
                
            except Exception as e:
                print(f'\n✗ ERROR in interval {interval_count} (blocks {current_start} to {interval_end}): {str(e)}')
                raise
            
            current_start = interval_end + 1
        
        print(f'\n✓ Successfully completed syncing {end - start + 1} blocks in {interval_count} intervals')
        
    except Exception as e:
        print(f'\n✗ CRITICAL ERROR: Sync failed at interval {interval_count}')
        print(f'Error: {str(e)}')
        sys.exit(1)
