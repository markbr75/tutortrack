import threading

import pytest
from django.db import connection, transaction

from tutortrack.core.context import tenant_context
from tutortrack.core.sequences import SequenceOutsideTransaction, next_number


@pytest.mark.django_db
def test_numbers_are_sequential_and_per_organisation(org, other_org):
    with tenant_context(org), transaction.atomic():
        assert next_number("invoice", prefix="INV-") == "INV-000001"
        assert next_number("invoice", prefix="INV-") == "INV-000002"
        assert next_number("credit_note", prefix="CN-", padding=4) == "CN-0001"
    with tenant_context(other_org), transaction.atomic():
        assert next_number("invoice", prefix="INV-") == "INV-000001"


@pytest.mark.django_db(transaction=True)
def test_rolled_back_transaction_does_not_burn_a_number(org):
    with tenant_context(org):
        with pytest.raises(RuntimeError), transaction.atomic():
            next_number("invoice")
            raise RuntimeError("invoice failed to save")
        with transaction.atomic():
            assert next_number("invoice") == "000001"


@pytest.mark.django_db(transaction=True)
def test_requires_transaction(org):
    with tenant_context(org), pytest.raises(SequenceOutsideTransaction):
        next_number("invoice")


@pytest.mark.django_db(transaction=True)
def test_concurrent_callers_get_unique_gap_free_numbers(org):
    results: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            with tenant_context(org):
                for _ in range(10):
                    with transaction.atomic():
                        number = next_number("invoice")
                    with lock:
                        results.append(number)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results) == [f"{n:06d}" for n in range(1, 51)]
