# -*- coding: utf-8 -*-
import inspect

import workers.publish as publish_mod


def test_publish_worker_registers_slot_with_scheduler():
    """publish_worker's postponed branch must call reserve_slot/record_slot
    so photos/videos/clips cycles see posts' reserved timestamps too."""
    source = inspect.getsource(publish_mod.publish_worker)
    assert "record_slot" in source or "reserve_slot" in source
