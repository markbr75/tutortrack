from rest_framework import pagination


class CursorPagination(pagination.CursorPagination):
    """Default pagination: opaque ``?cursor=``, newest first.

    UUIDv7 primary keys are time-ordered, so ``-id`` is a stable, indexed ordering for any
    model. Views may set ``ordering`` to something else that is unique and indexed.
    """

    ordering = "-id"
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200
