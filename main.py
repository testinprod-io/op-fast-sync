import os
import threading
import time

from apply_batch import PayloadApplier
from build_payloads import PayloadBuilder
from shared_state import SharedState
from utils import parse_args, send_json_rpc, RPCMethod

if __name__ == '__main__':
    args = parse_args()
    if not os.path.exists(args.payload_dir):
        os.makedirs(args.payload_dir)
        print(f'Created payload dir: {args.payload_dir}')

    # Handle trigger-sync mode
    if args.trigger_sync is not None:
        print(f'Trigger-sync mode: building and applying block {args.trigger_sync}')

        # Build payload for the specific block
        payload_builder = PayloadBuilder(
            args.payload_dir,
            args.l1_rpc_urls,
            args.l2_rpc_urls,
            args.canyon_time,
            args.ecotone_time,
            args.logging,
            shared_state=None
        )

        print(f'Building payload for block {args.trigger_sync}...')
        try:
            payload_builder.build(args.trigger_sync)
            print(f'Successfully built payload for block {args.trigger_sync}')
        except Exception as e:
            print(f'Failed to build payload for block {args.trigger_sync}: {e}')
            exit(1)

        # Apply the payload
        # Get safe and finalized info from L2 RPC
        safe_header = send_json_rpc(args.l2_rpc_urls[0], RPCMethod.GetBlockByNumber, params=['safe', False])
        safe_number = int(safe_header['number'], 16)
        safe_hash = safe_header['hash']

        finalized_header = send_json_rpc(args.l2_rpc_urls[0], RPCMethod.GetBlockByNumber, params=['finalized', False])
        finalized_number = int(finalized_header['number'], 16)
        finalized_hash = finalized_header['hash']

        payload_applier = PayloadApplier(
            args.engine_url,
            args.jwt_secret,
            args.payload_dir,
            args.trigger_sync,
            args.trigger_sync,
            1,  # batch_size = 1 for single block
            safe_number,
            safe_hash,
            finalized_number,
            finalized_hash,
            args.canyon_time,
            args.ecotone_time,
            args.logging,
            shared_state=None
        )

        print(f'Applying payload for block {args.trigger_sync}...')
        try:
            payload_applier.run()
            print(f'Successfully triggered EL sync with block {args.trigger_sync}')
            exit(0)
        except Exception as e:
            print(f'Failed to apply payload for block {args.trigger_sync}: {e}')
            exit(1)

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

    # Determine if we should use concurrent mode
    use_concurrent = args.concurrent and not args.sequential
    
    if use_concurrent:
        print("Using concurrent mode: building and applying will happen simultaneously")
        # Create shared state for concurrent building and applying
        shared_state = SharedState(start, end)

        payload_builder = PayloadBuilder(
            args.payload_dir,
            args.l1_rpc_urls,
            args.l2_rpc_urls,
            args.canyon_time,
            args.ecotone_time,
            args.logging,
            shared_state=shared_state
        )
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
            args.logging,
            shared_state=shared_state
        )

        # Create threads for concurrent building and applying
        def build_thread():
            print('Start building payloads')
            payload_builder.run_multiproc(start, end, args.num_proc)

        def apply_thread():
            print('Start applying payloads')
            payload_applier.run()

        # Start both threads
        builder = threading.Thread(target=build_thread, name="Builder")
        applier = threading.Thread(target=apply_thread, name="Applier")

        builder.start()
        # Give the builder a small head start to build a few blocks
        time.sleep(1)
        applier.start()

        # Wait for both to complete
        builder.join()
        applier.join()

        print('Both building and applying completed')
    else:
        print("Using sequential mode: building all payloads first, then applying them")
        # Sequential mode - build all, then apply all
        payload_builder = PayloadBuilder(
            args.payload_dir,
            args.l1_rpc_urls,
            args.l2_rpc_urls,
            args.canyon_time,
            args.ecotone_time,
            args.logging,
            shared_state=None
        )
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
            args.logging,
            shared_state=None
        )

        print('Start building payloads')
        payload_builder.run_multiproc(start, end, args.num_proc)

        print('Start applying payloads')
        payload_applier.run()
