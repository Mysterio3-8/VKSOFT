from config import app_state
from workers.media_autopilot import loop_download_count, loop_publish_count, loops_status


def test_media_loop_counts_use_separate_download_and_publish_settings(monkeypatch):
    profile = {
        'download_settings': {'posts_to_download': 42},
        'publishing_settings': {'posts_to_publish': 24},
        'photos_settings': {'photos_download_per_run': 12, 'photos_publish_per_run': 7},
        'videos_settings': {'videos_download_per_run': 8, 'videos_publish_per_run': 3},
        'clips_settings': {'clips_download_per_run': 6, 'clips_publish_per_run': 2},
    }
    monkeypatch.setitem(app_state.config, 'active_profile', 'test')
    monkeypatch.setitem(app_state.config, 'profiles', {'test': profile})

    assert loop_download_count('posts') == 42
    assert loop_publish_count('posts') == 24
    assert loop_download_count('photos') == 12
    assert loop_publish_count('photos') == 7
    assert loop_download_count('videos') == 8
    assert loop_publish_count('videos') == 3
    assert loop_download_count('clips') == 6
    assert loop_publish_count('clips') == 2

    status = loops_status()
    assert status['posts']['download_count'] == 42
    assert status['posts']['publish_count'] == 24
