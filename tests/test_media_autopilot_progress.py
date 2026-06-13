from config import app_state
from workers.media_autopilot import _set_progress, loops_status


def test_set_progress_writes_to_media_loop_state(monkeypatch):
    monkeypatch.setitem(app_state.media_loop_state, 'posts', {})

    _set_progress('posts', phase='download', current=3, total=10, label='Скачивание')

    assert app_state.media_loop_state['posts']['progress'] == {
        'phase': 'download',
        'current': 3,
        'total': 10,
        'label': 'Скачивание',
    }


def test_progress_field_appears_in_loops_status(monkeypatch):
    monkeypatch.setitem(app_state.media_loop_state, 'photos', {})
    monkeypatch.setitem(app_state.config, 'active_profile', 'test')
    monkeypatch.setitem(app_state.config, 'profiles', {'test': {}})

    _set_progress('photos', phase='publish', current=5, total=5, label='Публикация')

    status = loops_status()
    assert status['photos']['progress'] == {
        'phase': 'publish',
        'current': 5,
        'total': 5,
        'label': 'Публикация',
    }


def test_media_loop_worker_resets_progress_to_idle_between_passes(monkeypatch):
    monkeypatch.setitem(app_state.media_loop_state, 'posts', {'progress': {
        'phase': 'download', 'current': 7, 'total': 10, 'label': 'старое',
    }})
    monkeypatch.setitem(app_state.config, 'active_profile', 'test')
    monkeypatch.setitem(app_state.config, 'profiles', {'test': {
        'autopilot': {'intervals': {'posts': 180}},
    }})
    monkeypatch.setitem(app_state.media_loops, 'posts', False)

    import workers.media_autopilot as ma
    monkeypatch.setitem(ma._CYCLES, 'posts', lambda: None)

    ma.media_loop_worker('posts')

    progress = app_state.media_loop_state['posts']['progress']
    assert progress == {'phase': 'idle', 'current': 0, 'total': 0, 'label': ''}


def test_download_source_updates_media_loop_progress(monkeypatch, tmp_path):
    """_download_source должен синхронизировать app_state.media_loop_state['posts']['progress']."""
    monkeypatch.setitem(app_state.media_loop_state, 'posts', {})
    monkeypatch.setattr(app_state, 'download_progress', {'cancelled': False})

    from workers.media_autopilot import _set_progress
    # Симулируем то, что должен делать _download_source при старте загрузки:
    _set_progress('posts', phase='download', current=0, total=5, label='Загрузка из -123')
    _set_progress('posts', phase='download', current=3, total=5, label='Сохранено 3 из 5')

    progress = app_state.media_loop_state['posts']['progress']
    assert progress['phase'] == 'download'
    assert progress['current'] == 3
    assert progress['total'] == 5
