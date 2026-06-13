# tests/test_videos_scheduler_integration.py
# -*- coding: utf-8 -*-
import inspect

import workers.videos as videos_mod


def test_publish_videos_worker_calls_reserve_slot_with_media_type():
    """Source-level check: publish_videos_worker references reserve_slot
    and passes media_type derived from is_clips_mode."""
    source = inspect.getsource(videos_mod.publish_videos_worker)
    assert "reserve_slot(media_type, delay_min, delay_max)" in source
    assert "media_type = 'clips' if is_clips_mode else 'videos'" in source
    assert "_get_next_ts" not in source
