# -*- coding: utf-8 -*-
import inspect

import workers.publish as publish_mod
import workers.photos as photos_mod
import workers.videos as videos_mod


def test_all_publish_workers_call_log_publish_event():
    for mod, fn_name in (
        (publish_mod, "publish_worker"),
        (photos_mod, "publish_photos_worker"),
        (videos_mod, "publish_videos_worker"),
    ):
        source = inspect.getsource(getattr(mod, fn_name))
        assert "log_publish_event" in source, f"{fn_name} missing log_publish_event call"
