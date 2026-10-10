import pytest


@pytest.fixture(autouse=True)
def plans(db: None) -> None:
    """Transactional tests flush the platform plan tables: put the catalogue back."""
    from tutortrack.subscriptions.catalogue import sync_plans

    sync_plans()
