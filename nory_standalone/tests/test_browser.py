"""Opt-in actual Chromium tests; the offline unit suite needs no browser download."""

import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("NORY_BROWSER_TESTS") != "1",
    reason="Enable NORY_BROWSER_TESTS=1 for actual browser checks",
)


@pytest.fixture(scope="module")
def browser_app(tmp_path_factory):
    from playwright.sync_api import sync_playwright

    root = Path(__file__).resolve().parents[2]
    folder = tmp_path_factory.mktemp("browser")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    output = (folder / "server.log").open("w")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "nory_standalone",
            "--offline",
            "--no-browser",
            "--port",
            str(port),
            "--db",
            str(folder / "nory.sqlite3"),
        ],
        cwd=root,
        stdout=output,
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(150):
            try:
                with urlopen(url + "/api/session", timeout=0.5):
                    break
            except OSError:
                if process.poll() is not None:
                    raise RuntimeError((folder / "server.log").read_text())
                time.sleep(0.1)
        else:
            raise RuntimeError("Browser app startup timed out")
        with sync_playwright() as p:
            opts = {"headless": True}
            if os.environ.get("NORY_CHROMIUM_EXECUTABLE"):
                opts["executable_path"] = os.environ["NORY_CHROMIUM_EXECUTABLE"]
            browser = p.chromium.launch(**opts)
            yield browser, url, folder
            browser.close()
    finally:
        process.terminate()
        process.wait(timeout=10)
        output.close()


@pytest.mark.parametrize("width,height", [(1440, 1000), (768, 1024), (390, 844)])
def test_four_sections_tabs_controls_and_responsive_layout(browser_app, width, height):
    from playwright.sync_api import expect

    browser, url, folder = browser_app
    page = browser.new_page(viewport={"width": width, "height": height})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    token = page.request.get(url + "/api/session").json()["token"]
    page.request.post(url + "/api/stop", headers={"X-Nory-Token": token})
    page.goto(url)
    expect(page.locator("#start")).to_be_enabled()
    assert page.locator("#capital").inner_text() == "$10,000.00"
    page.locator("#start").click()
    expect(page.locator("#engine-status")).to_have_text("Nory en ejecución")
    for section in ("dashboard", "markets", "operations", "intelligence"):
        page.locator(f"[data-view={section}]").click()
        assert page.locator(f"#{section}-view").is_visible()
        assert page.locator("#engine-status").inner_text() == "Nory en ejecución"
        assert not page.evaluate("document.documentElement.scrollWidth>innerWidth"), (
            section
        )
        page.screenshot(path=str(folder / f"{section}-{width}.png"), full_page=True)
    for tab in ("strategies", "risk", "research", "diagnostics", "performance"):
        page.locator(f"[data-intelligence={tab}]").click()
        assert page.locator("#intelligence-content").inner_text()
    page.locator("#strategy").select_option("cash")
    expect(page.locator("#stop")).to_be_enabled()
    page.locator("#stop").click()
    expect(page.locator("#engine-status")).to_have_text("Nory detenido")
    assert not errors
    page.close()
