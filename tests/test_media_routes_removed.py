from main import app


def test_manual_media_routes_are_not_registered():
    paths = {route.path for route in app.routes}
    assert not any(path.startswith('/api/media/') for path in paths)
    assert '/api/media/status' not in paths
    assert '/api/growth/bot_changes' not in paths
