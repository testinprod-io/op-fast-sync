import threading
import time


class SharedState:
    """Thread-safe shared state for tracking payload building progress."""

    def __init__(self, start_block, end_block):
        self.start_block = start_block
        self.end_block = end_block
        self.built_blocks = set()
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)
        self.building_complete = False
        self.builder_failed = False

    def mark_built(self, block_number):
        """Mark a block as built and notify waiting threads."""
        with self.condition:
            self.built_blocks.add(block_number)
            self.condition.notify_all()

    def mark_building_complete(self):
        """Mark that all building is complete."""
        with self.condition:
            self.building_complete = True
            self.condition.notify_all()

    def mark_builder_failed(self):
        """Mark that the builder has failed."""
        with self.condition:
            self.builder_failed = True
            self.condition.notify_all()

    def get_highest_consecutive_built(self, from_block):
        """
        Get the highest consecutive block number that has been built starting from from_block.
        Returns the last consecutive block number.
        """
        with self.lock:
            current = from_block
            while current in self.built_blocks and current <= self.end_block:
                current += 1
            return current - 1

    def wait_for_blocks(self, current_synced_block, batch_size, timeout=None):
        """
        Wait until at least batch_size blocks are available ahead of current_synced_block,
        or building is complete.

        Returns:
            True if blocks are available or building is complete
            False if timeout occurred
        """
        start_time = time.time()

        with self.condition:
            while True:
                # Check if builder has failed
                if self.builder_failed:
                    return False

                # Get the highest consecutive built block
                highest_built = self.get_highest_consecutive_built(current_synced_block + 1)
                blocks_available = highest_built - current_synced_block

                # Check if we have enough blocks or building is complete
                if blocks_available >= batch_size or self.building_complete:
                    return True

                # Check timeout
                if timeout is not None:
                    elapsed = time.time() - start_time
                    if elapsed >= timeout:
                        return False
                    remaining_timeout = timeout - elapsed
                else:
                    remaining_timeout = None

                # Wait for notification
                self.condition.wait(timeout=remaining_timeout)

    def get_stats(self):
        """Get statistics about building progress."""
        with self.lock:
            total_blocks = self.end_block - self.start_block + 1
            built_count = len(self.built_blocks)
            return {
                'total': total_blocks,
                'built': built_count,
                'building_complete': self.building_complete,
                'builder_failed': self.builder_failed,
            }
