# -*- coding: utf-8 -*-
"""Module: CROSS-BROWSER / Selenium regression lane.

WHY SELENIUM IS HERE AND WHAT IT IS FOR. Playwright is the primary framework and covers
the behaviour. Selenium adds the one thing it cannot: the REAL, vendor-shipped browsers
an analyst actually opens -- a system Chrome, a system Firefox, and (on macOS) Safari
through safaridriver -- rather than Playwright's bundled builds. So this file
deliberately does NOT re-test the feed, the filters or the pagination. It runs the
smallest set that would catch a browser-specific break:

  - does the app boot at all (React 18 + the vite bundle's target)
  - does hash routing work (history/popstate differ across engines)
  - does the rail respond to a real click
  - do the fonts and the layout give a usable width
  - does the operator console load

Basic auth: Selenium cannot set httpCredentials the way Playwright can, so the
credential is put in the URL when one is configured. That works in Chrome and Firefox
for a same-document navigation, which is all this lane does.

Run:  pytest tests/frontend/selenium -v
      KSSL_TEST_BROWSERS=chrome,firefox pytest tests/frontend/selenium
"""
import os
import sys
import time
from urllib.parse import urlsplit, urlunsplit

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from lib import env  # noqa: E402

selenium = pytest.importorskip("selenium", reason="pip install -r tests/requirements.txt")
from selenium import webdriver  # noqa: E402
from selenium.common.exceptions import WebDriverException  # noqa: E402
from selenium.webdriver.common.by import By  # noqa: E402
from selenium.webdriver.support import expected_conditions as EC  # noqa: E402
from selenium.webdriver.support.ui import WebDriverWait  # noqa: E402

BROWSERS = [b.strip() for b in
            os.environ.get("KSSL_TEST_BROWSERS", "chrome,firefox").split(",") if b.strip()]
HEADLESS = os.environ.get("KSSL_TEST_HEADED") != "1"


def _auth_url(url):
    """Put the basic-auth credential in the URL. Only used when one is configured."""
    if not env.BASIC_USER:
        return url
    parts = urlsplit(url)
    netloc = "%s:%s@%s" % (env.BASIC_USER, env.BASIC_PW, parts.netloc)
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _driver(name):
    try:
        if name == "chrome":
            o = webdriver.ChromeOptions()
            if HEADLESS:
                o.add_argument("--headless=new")
            o.add_argument("--window-size=1440,900")
            o.add_argument("--ignore-certificate-errors")
            return webdriver.Chrome(options=o)
        if name == "firefox":
            o = webdriver.FirefoxOptions()
            if HEADLESS:
                o.add_argument("-headless")
            o.set_preference("network.http.phishy-userpass-length", 255)
            o.accept_insecure_certs = True
            d = webdriver.Firefox(options=o)
            d.set_window_size(1440, 900)
            return d
        if name == "safari":
            return webdriver.Safari()      # safaridriver must be enabled by the operator
        if name == "edge":
            o = webdriver.EdgeOptions()
            if HEADLESS:
                o.add_argument("--headless=new")
            return webdriver.Edge(options=o)
    except WebDriverException as exc:
        pytest.skip("%s webdriver unavailable: %s" % (name, exc))
    pytest.skip("unknown browser %s" % name)


@pytest.fixture(params=BROWSERS)
def driver(request):
    d = _driver(request.param)
    d.set_page_load_timeout(90)
    yield d
    d.quit()


def _boot(driver, hash_=""):
    driver.get(_auth_url(env.front("/" + hash_)))
    WebDriverWait(driver, 60).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".rail")))


def test_xb_001_app_boots(driver):
    """
    Test ID        : XB-001
    Module         : Cross-browser / Bootstrap
    Precondition   : the browser's driver is installed; the app is served
    Steps          : 1. open /  2. wait for .rail  3. read the wordmark
    Test Data      : none
    Expected Result: the shell renders in this browser. The bundle is built by vite for
                     the browsers listed in the project's build target; a boot failure
                     here and nowhere else is a transpilation or API-support gap.
    API Endpoint   : GET /api/dataset
    DB Validation  : n/a
    Priority       : P0
    Automation Tool: Selenium WebDriver
    """
    _boot(driver)
    assert "137" in driver.find_element(By.CSS_SELECTOR, ".wordmark").text


def test_xb_002_no_dataset_error_text(driver):
    """
    Test ID        : XB-002
    Module         : Cross-browser / Bootstrap failure detection
    Precondition   : XB-001
    Steps          : 1. open /  2. read the body text
    Test Data      : none
    Expected Result: none of DataProvider's error strings are on screen. A browser whose
                     fetch is blocked (mixed content, a cert, a cookie policy) shows the
                     shell's error, not a crash -- so the text is the detector.
    API Endpoint   : GET /api/dataset
    DB Validation  : n/a
    Priority       : P0
    Automation Tool: Selenium WebDriver
    """
    _boot(driver)
    body = driver.find_element(By.TAG_NAME, "body").text
    assert "did not return a usable dataset" not in body
    assert "is the backend running on port 8600" not in body


def test_xb_003_hash_routing(driver):
    """
    Test ID        : XB-003
    Module         : Cross-browser / Routing
    Precondition   : XB-001
    Steps          : 1. open #p=technology&v=innovation directly
                     2. assert the rail renders and the hash survived
                     3. navigate to another view and press Back
    Test Data      : #p=technology&v=innovation, #p=market&v=tender
    Expected Result: the route resolves and Back returns. history.pushState/popstate
                     behaviour is the classic cross-engine difference, and this app's
                     entire navigation rides on it.
    API Endpoint   : none
    DB Validation  : n/a
    Priority       : P0
    Automation Tool: Selenium WebDriver
    """
    _boot(driver, "#p=technology&v=innovation")
    assert "v=innovation" in driver.current_url
    driver.get(_auth_url(env.front("/#p=market&v=tender")))
    WebDriverWait(driver, 60).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".rail")))
    driver.back()
    WebDriverWait(driver, 30).until(lambda d: "v=innovation" in d.current_url)


def test_xb_004_rail_click_navigates(driver):
    """
    Test ID        : XB-004
    Module         : Cross-browser / Interaction
    Precondition   : XB-001
    Steps          : 1. open the competitive overview
                     2. click the second rail row
                     3. assert it takes the active class
    Test Data      : the competitive rail
    Expected Result: a real click on a role="button" div navigates in every engine.
    API Endpoint   : none
    DB Validation  : n/a
    Priority       : P0
    Automation Tool: Selenium WebDriver
    """
    _boot(driver, "#p=competitive&v=overview")
    rows = driver.find_elements(By.CSS_SELECTOR, ".rail .svc")
    assert len(rows) > 1
    rows[1].click()
    WebDriverWait(driver, 20).until(
        lambda d: "active" in d.find_elements(By.CSS_SELECTOR, ".rail .svc")[1]
                                .get_attribute("class"))


def test_xb_005_no_horizontal_overflow(driver):
    """
    Test ID        : XB-005
    Module         : Cross-browser / Layout
    Precondition   : XB-001
    Steps          : 1. open the competitive overview at 1440x900
                     2. compare documentElement.scrollWidth to clientWidth
    Test Data      : 1440x900
    Expected Result: no page-level horizontal scrollbar. Font metrics differ per engine,
                     and this repository has already shipped a rail label that rendered
                     truncated at every viewport including 1920.
    API Endpoint   : none
    DB Validation  : n/a
    Priority       : P2
    Automation Tool: Selenium WebDriver
    """
    _boot(driver, "#p=competitive&v=overview")
    over = driver.execute_script(
        "return document.documentElement.scrollWidth - document.documentElement.clientWidth;")
    assert over <= 2, "horizontal overflow of %spx" % over


def test_xb_006_rail_labels_are_not_truncated(driver):
    """
    Test ID        : XB-006
    Module         : Cross-browser / Layout (regression)
    Precondition   : XB-001
    Steps          : 1. open each pillar
                     2. for every rail label, compare scrollWidth to clientWidth
    Test Data      : all three rails
    Expected Result: no label overflows its slot. "Innovation Pipeline" needed 119px of
                     a 107px slot and rendered "Innovation Pip..." at EVERY viewport --
                     which is why the rail label is "Innovations" and the page title is
                     not.
    API Endpoint   : none
    DB Validation  : n/a
    Priority       : P2
    Automation Tool: Selenium WebDriver
    """
    clipped = []
    for pillar, view in (("competitive", "overview"), ("market", "m-overview"),
                         ("technology", "t-overview")):
        _boot(driver, "#p=%s&v=%s" % (pillar, view))
        for el in driver.find_elements(By.CSS_SELECTOR, ".rail .svc .nm"):
            sw = driver.execute_script("return arguments[0].scrollWidth;", el)
            cw = driver.execute_script("return arguments[0].clientWidth;", el)
            if cw and sw > cw + 1:
                clipped.append("%s/%s: %s (%s>%s)" % (pillar, view, el.text, sw, cw))
    assert not clipped, "rail labels clipped: %s" % clipped


def test_xb_007_ops_console_loads(driver):
    """
    Test ID        : XB-007
    Module         : Cross-browser / Operator console
    Precondition   : the frontend container is serving /ops/
    Steps          : 1. open /ops/  2. read the h1
    Test Data      : none
    Expected Result: "Backend Intelligence". The console is plain ES2017 with no build
                     step, so it is the page most likely to differ across engines.
    API Endpoint   : GET /api/ops/overview (loaded by the page)
    DB Validation  : n/a
    Priority       : P1
    Automation Tool: Selenium WebDriver
    """
    driver.get(_auth_url(env.front("/ops/")))
    WebDriverWait(driver, 60).until(
        EC.presence_of_element_located((By.TAG_NAME, "h1")))
    assert "Backend Intelligence" in driver.find_element(By.TAG_NAME, "h1").text


def test_xb_008_no_console_errors_on_boot(driver):
    """
    Test ID        : XB-008
    Module         : Cross-browser / Runtime errors
    Precondition   : XB-001; the driver exposes a browser log (chrome/edge only)
    Steps          : 1. open /  2. read the browser log at SEVERE level
    Test Data      : none
    Expected Result: no SEVERE entries. esbuild does not resolve free identifiers, so a
                     call to a function that has never existed builds green and throws
                     only when that line runs -- formatTitleCase sat in a useMemo in
                     Products.jsx and took the whole view down on staging past
                     `npm run build` and every check below it.
    API Endpoint   : GET /api/dataset
    DB Validation  : n/a
    Priority       : P1
    Automation Tool: Selenium WebDriver
    """
    _boot(driver)
    try:
        logs = driver.get_log("browser")
    except Exception:                                    # noqa: BLE001
        pytest.skip("this driver does not expose a browser log")
    severe = [l for l in logs if l.get("level") == "SEVERE"
              and "favicon" not in (l.get("message") or "")]
    assert not severe, "SEVERE console entries on boot: %s" % severe[:5]


def test_xb_009_boot_time_is_measured(driver):
    """
    Test ID        : XB-009 / PERF-020
    Module         : Cross-browser / Performance
    Precondition   : XB-001
    Steps          : 1. time the load until .rail appears
    Test Data      : budget = KSSL_TEST_BUDGET_PAINT_S (default 45s)
    Expected Result: under budget in every browser, and the number is printed so the
                     report carries a measured figure per engine rather than one.
    API Endpoint   : GET /api/dataset
    DB Validation  : n/a
    Priority       : P2
    Automation Tool: Selenium WebDriver
    """
    t0 = time.time()
    _boot(driver)
    dt = time.time() - t0
    print("XB-009 boot time in %s: %.1fs" % (driver.name, dt))
    assert dt < env.BUDGET_FIRST_PAINT_S
