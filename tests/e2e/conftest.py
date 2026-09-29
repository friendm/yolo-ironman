"""Playwright smoke tests: run with `pytest -m e2e`. Every flow runs with JavaScript disabled at 375px."""

import importlib
import os

import pytest

# Playwright's sync API runs an event loop in this thread; the ORM calls in these tests are still synchronous.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    executable = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    return {**browser_type_launch_args, **({"executable_path": executable} if executable else {})}


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {**browser_context_args, "java_script_enabled": False, "viewport": {"width": 375, "height": 812}}


@pytest.fixture
def seeded(transactional_db):
    """Transactional tests flush data migrations, so seed the document types again."""
    from django.apps import apps

    importlib.import_module("documents.migrations.0003_seed_document_types").seed(apps, None)


@pytest.fixture
def sample_png(tmp_path):
    from ops import sample_docs

    path = tmp_path / "permit.png"
    path.write_bytes(sample_docs.permit("Health permit", "Smoke Test Tacos", "Fulton County", "FC-1"))
    return path


def last_code(phone):
    from notifications.models import Notification

    return Notification.objects.filter(template="otp", to=phone).latest("created_at").payload["code"]


def assert_fits_phone(page):
    width = page.evaluate("document.documentElement.scrollWidth")
    assert width <= 375, f"{page.url} scrolls horizontally ({width}px)"
