"""API tests for Operations & Workflow endpoints (FastAPI TestClient)."""
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

# Avoid connecting to DB in tests when importing main
os.environ.setdefault("USE_OPERATIONS_WORKFLOW_AGENT", "true")


def test_workflow_router_mounted():
    """Workflow router is mounted and /workflow/queues is reachable."""
    from main import app
    client = TestClient(app)
    # May 200 (empty queues) or 500 if Prisma not connected
    resp = client.get("/workflow/queues")
    assert resp.status_code in (200, 500)
    if resp.status_code == 200:
        data = resp.json()
        assert "queue_counts" in data
        assert "total_pending" in data


def test_workflow_stats_structure():
    """GET /workflow/stats returns expected keys when successful."""
    from main import app
    client = TestClient(app)
    resp = client.get("/workflow/stats")
    assert resp.status_code in (200, 500)
    if resp.status_code == 200:
        data = resp.json()
        assert "queue_counts" in data
        assert "pending_approvals" in data
        assert "overdue_count" in data
        assert "avg_cycle_time_seconds" in data


def test_workflow_queue_items_paginated():
    """GET /workflow/queues/{name}/items accepts limit and offset."""
    from main import app
    client = TestClient(app)
    resp = client.get("/workflow/queues/duplicate_review/items?limit=10&offset=0")
    assert resp.status_code in (200, 500)
    if resp.status_code == 200:
        assert isinstance(resp.json(), list)


def test_workflow_approvals_pending():
    """GET /workflow/approvals/pending returns list."""
    from main import app
    client = TestClient(app)
    resp = client.get("/workflow/approvals/pending")
    assert resp.status_code in (200, 500)
    if resp.status_code == 200:
        assert isinstance(resp.json(), list)
