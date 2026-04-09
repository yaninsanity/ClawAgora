import pytest
from django.core.cache import cache
from rest_framework.settings import api_settings


@pytest.fixture(autouse=True)
def _disable_throttle(settings):
    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "DEFAULT_THROTTLE_CLASSES": [],
        "DEFAULT_THROTTLE_RATES": {},
    }
    api_settings.reload()


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    cache.clear()


@pytest.fixture(autouse=True)
def _reset_orchestration():
    from orchestration.services import reset_orchestration_service

    reset_orchestration_service()
    yield
    reset_orchestration_service()
