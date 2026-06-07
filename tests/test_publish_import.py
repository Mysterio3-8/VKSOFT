# -*- coding: utf-8 -*-


def test_publish_worker_imports():
    import workers.publish as publish

    assert callable(publish.publish_worker)
