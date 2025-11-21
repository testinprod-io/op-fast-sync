import os
import threading
import time

from apply_batch import PayloadApplier
from build_payloads import PayloadBuilder
from shared_state import SharedState
from utils import parse_args, send_json_rpc, RPCMethod


def trigger_sync_for_block(block_number, args):
    """Build and apply a single block to trigger EL sync."""
    import json
    import jwt as pyjwt

    # Build payload for the specific block
    payload_builder = PayloadBuilder(
        args.payload_dir,
        args.l1_rpc_urls,
        args.l2_rpc_urls,
        args.canyon_time,
        args.ecotone_time,
        args.isthmus_time,
        args.logging,
        shared_state=None
    )

    print(f'Building payload for block {block_number}...')
    try:
        payload_builder.build(block_number)
        print(f'Successfully built payload for block {block_number}')
    except Exception as e:
        print(f'Failed to build payload for block {block_number}: {e}')
        raise

    # Apply the payload - send newPayload and forkchoiceUpdated once
    payload_file = os.path.join(args.payload_dir, f'{hex(block_number)}.json')
    with open(payload_file, 'r') as f:
        payload_array = json.load(f)

    payload = payload_array[0]
    timestamp = int(payload['timestamp'], 16)
    payload_version = 4 if timestamp >= args.isthmus_time else 3 if timestamp >= args.ecotone_time else 2 if timestamp >= args.canyon_time else 1
    # forkchoiceUpdated stays at V3 for Isthmus (V4 is only for newPayload/getPayload)
    fcu_version = 3 if timestamp >= args.ecotone_time else 2 if timestamp >= args.canyon_time else 1

    # Get JWT token
    with open(args.jwt_secret, 'r') as f:
        jwt_secret = f.readline().strip()

    auth_payload = {'iat': int(time.time())}
    jwt_token = pyjwt.encode(
        auth_payload,
        bytes.fromhex(jwt_secret[2:] if jwt_secret.startswith('0x') else jwt_secret)
    )

    # Get safe and finalized info
    safe_header = send_json_rpc(args.l2_rpc_urls[0], RPCMethod.GetBlockByNumber, params=['safe', False])
    safe_hash = safe_header['hash']

    finalized_header = send_json_rpc(args.l2_rpc_urls[0], RPCMethod.GetBlockByNumber, params=['finalized', False])
    finalized_hash = finalized_header['hash']

    print(f'Sending newPayloadV{payload_version} for block {block_number}...')
    try:
        send_json_rpc(args.engine_url, f'engine_newPayloadV{payload_version}', params=payload_array, token=jwt_token, timeout=60)
        print(f'Successfully sent newPayload')
    except Exception as e:
        print(f'Failed to send newPayload: {e}')
        raise

    print(f'Sending forkchoiceUpdatedV{fcu_version} for block {block_number}...')
    try:
        send_json_rpc(
            args.engine_url,
            f'engine_forkchoiceUpdatedV{fcu_version}',
            params=[{
                'headBlockHash': payload['blockHash'],
                'safeBlockHash': safe_hash,
                'finalizedBlockHash': finalized_hash,
            }],
            token=jwt_token,
            timeout=60,
        )
        print(f'Successfully sent forkchoiceUpdated')
    except Exception as e:
        print(f'Warning: forkchoiceUpdated call failed/timed out: {e}')
        print(f'Continuing anyway - will retry periodically if using trigger-sync-list')

    print(f'EL sync triggered with block {block_number}')


if __name__ == '__main__':
    args = parse_args()

    # Configure rate limiter based on command-line argument
    from utils import _rate_limiter_manager
    _rate_limiter_manager.set_rate(args.rate_limit)
    print(f'Rate limiter configured: {args.rate_limit} requests/second per endpoint')

    if not os.path.exists(args.payload_dir):
        os.makedirs(args.payload_dir)
        print(f'Created payload dir: {args.payload_dir}')

    # Handle trigger-sync mode
    if args.trigger_sync is not None:
        print(f'Trigger-sync mode: building and applying block {args.trigger_sync}')
        try:
            trigger_sync_for_block(args.trigger_sync, args)
            exit(0)
        except Exception as e:
            print(f'Failed to trigger sync for block {args.trigger_sync}: {e}')
            exit(1)

    # Handle trigger-sync-list mode
    if args.trigger_sync_list is not None:
        print(f'Trigger-sync-list mode: {args.trigger_sync_list}')
        try:
            block_list = [int(b.strip()) for b in args.trigger_sync_list.split(',')]
            print(f'Will trigger sync for blocks: {block_list}')
        except Exception as e:
            print(f'Failed to parse trigger-sync-list: {e}')
            exit(1)

        for i, block_number in enumerate(block_list):
            print(f'\n=== Processing block {block_number} ({i+1}/{len(block_list)}) ===')

            # Trigger sync for this block
            try:
                trigger_sync_for_block(block_number, args)
            except Exception as e:
                print(f'Failed to trigger sync for block {block_number}: {e}')
                exit(1)

            # If this is not the last block, wait for the engine to sync to this block
            if i < len(block_list) - 1:
                print(f'\nWaiting for engine to sync to block {block_number}...')
                poll_interval = 60  # 1 minute

                # Get payload info for resending forkchoiceUpdated
                import json
                import jwt as pyjwt

                payload_file = os.path.join(args.payload_dir, f'{hex(block_number)}.json')
                with open(payload_file, 'r') as f:
                    payload_array = json.load(f)
                payload = payload_array[0]
                timestamp = int(payload['timestamp'], 16)
                payload_version = 4 if timestamp >= args.isthmus_time else 3 if timestamp >= args.ecotone_time else 2 if timestamp >= args.canyon_time else 1
                # forkchoiceUpdated stays at V3 for Isthmus (V4 is only for newPayload/getPayload)
                fcu_version = 3 if timestamp >= args.ecotone_time else 2 if timestamp >= args.canyon_time else 1

                # Get JWT token
                with open(args.jwt_secret, 'r') as f:
                    jwt_secret = f.readline().strip()

                # Get safe and finalized info
                safe_header = send_json_rpc(args.l2_rpc_urls[0], RPCMethod.GetBlockByNumber, params=['safe', False])
                safe_hash = safe_header['hash']

                finalized_header = send_json_rpc(args.l2_rpc_urls[0], RPCMethod.GetBlockByNumber, params=['finalized', False])
                finalized_hash = finalized_header['hash']

                while True:
                    try:
                        result = send_json_rpc(args.rpc_url, RPCMethod.BlockNumber, params=[])
                        current_block = int(result, 16)
                        print(f'Engine at block {current_block}, waiting for {block_number}...')

                        if current_block >= block_number:
                            print(f'Engine has reached block {block_number}!')
                            break

                        # Resend forkchoiceUpdated to nudge the engine
                        print(f'Resending forkchoiceUpdatedV{fcu_version} for block {block_number}...')
                        try:
                            auth_payload = {'iat': int(time.time())}
                            jwt_token = pyjwt.encode(
                                auth_payload,
                                bytes.fromhex(jwt_secret[2:] if jwt_secret.startswith('0x') else jwt_secret)
                            )
                            send_json_rpc(
                                args.engine_url,
                                f'engine_forkchoiceUpdatedV{fcu_version}',
                                params=[{
                                    'headBlockHash': payload['blockHash'],
                                    'safeBlockHash': safe_hash,
                                    'finalizedBlockHash': finalized_hash,
                                }],
                                token=jwt_token,
                                timeout=60,
                            )
                            print(f'Successfully resent forkchoiceUpdated')
                        except Exception as e:
                            print(f'Error resending forkchoiceUpdated: {e}')

                        print(f'Waiting {poll_interval} seconds before next check...')
                        time.sleep(poll_interval)
                    except Exception as e:
                        print(f'Error polling engine: {e}. Retrying in {poll_interval} seconds...')
                        time.sleep(poll_interval)

        print(f'\nAll blocks in trigger-sync-list completed!')
        exit(0)

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
            args.isthmus_time,
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
            args.isthmus_time,
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
            args.isthmus_time,
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
            args.isthmus_time,
            args.logging,
            shared_state=None
        )

        print('Start building payloads')
        payload_builder.run_multiproc(start, end, args.num_proc)

        print('Start applying payloads')
        payload_applier.run()
