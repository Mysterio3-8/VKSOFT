# -*- coding: utf-8 -*-

import socket
import subprocess
import sys
import time
import urllib.request

import pytest
from playwright.sync_api import sync_playwright


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def live_server():
    port = _free_port()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 30
    while time.time() < deadline:
        if proc.poll() is not None:
            stderr = proc.stderr.read() if proc.stderr else ""
            raise RuntimeError(f"Server exited early: {stderr}")
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=1) as response:
                if response.status == 200:
                    yield base_url
                    break
        except Exception:
            time.sleep(0.25)
    else:
        proc.terminate()
        raise RuntimeError("Server did not start")

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_main_user_tabs_render_without_console_errors(live_server):
    console_errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 950})
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.goto(live_server, wait_until="networkidle")

        assert page.locator("#dashboard.tab-content.active").is_visible()
        assert page.locator("#btnDownloadMenu").count() == 0
        assert page.locator("#quickPublishCount").count() == 0
        assert page.locator("#btnPublishQueue").count() == 0
        assert page.locator("#downloadProgressText").count() == 0
        assert page.locator('.nav-item[data-tab="monitor"]').count() == 0
        assert page.locator("#monitor").count() == 0
        assert page.locator('.nav-item[data-tab="media"]').count() == 0
        assert page.locator("#media").count() == 0
        assert page.locator("#gaBotChangesBody").count() == 0
        assert page.locator("#gaBotChangesList").count() == 0
        assert page.locator('button[data-settings="polls"]').count() == 0
        assert page.locator("#settings-polls").count() == 0
        for cycle_type in ["posts", "photos", "videos", "clips"]:
            assert page.locator(f"#apCycleSettings-{cycle_type}").count() == 1
            assert page.locator(f"#apInterval-{cycle_type}").count() == 1
            assert page.locator(f"#apDownload-{cycle_type}").count() == 1
            assert page.locator(f"#apPublish-{cycle_type}").count() == 1
            assert page.locator(f"#apSave-{cycle_type}").count() == 1

        for tab_id in ["channels", "settings", "library", "allstats", "logs"]:
            page.locator(f'.nav-item[data-tab="{tab_id}"]').click()
            page.wait_for_timeout(250)
            assert page.locator(f"#{tab_id}.tab-content.active").is_visible()

        browser.close()

    assert console_errors == []
