"""Tests for Matching & ERP Agent: demo adapter, stub, matching logic, processor."""
import os
import sys
from pathlib import Path

import pytest

_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

os.environ.setdefault("USE_MATCHING_ERP_AGENT", "true")
os.environ.setdefault("ERP_TYPE", "demo")


@pytest.mark.asyncio
async def test_demo_adapter_get_po():
    """Demo adapter returns PO for PO-DEMO-001."""
    from agents.matching_erp.adapters.demo import DemoERPAdapter

    adapter = DemoERPAdapter()
    po = await adapter.get_po("PO-DEMO-001")
    assert po is not None
    assert po.po_number == "PO-DEMO-001"
    assert po.total == 1500.00
    assert len(po.line_items) == 2


@pytest.mark.asyncio
async def test_demo_adapter_get_po_not_found():
    """Demo adapter returns None for unknown PO."""
    from agents.matching_erp.adapters.demo import DemoERPAdapter

    adapter = DemoERPAdapter()
    po = await adapter.get_po("PO-UNKNOWN")
    assert po is None


@pytest.mark.asyncio
async def test_demo_adapter_get_grns():
    """Demo adapter returns GRNs for po-demo-001."""
    from agents.matching_erp.adapters.demo import DemoERPAdapter

    adapter = DemoERPAdapter()
    grns = await adapter.get_grns_for_po("po-demo-001")
    assert len(grns) >= 1
    assert grns[0].po_id == "po-demo-001"


@pytest.mark.asyncio
async def test_demo_adapter_validate_vendor():
    """Demo adapter validates known vendor."""
    from agents.matching_erp.adapters.demo import DemoERPAdapter

    adapter = DemoERPAdapter()
    r = adapter.validate_vendor("Acme Corp")
    assert r.valid is True
    assert r.erp_id is not None
    r2 = adapter.validate_vendor("Unknown Vendor XYZ")
    assert r2.valid is False


@pytest.mark.asyncio
async def test_stub_adapter_returns_none():
    """Stub adapter returns None for get_po, empty for get_grns."""
    from agents.matching_erp.adapters.stub import StubERPAdapter

    adapter = StubERPAdapter()
    po = await adapter.get_po("ANY")
    assert po is None
    grns = await adapter.get_grns_for_po("ANY")
    assert grns == []


def test_run_matching_no_po():
    """run_matching with no PO returns match_status no_po."""
    from agents.matching_erp.matching import run_matching

    extracted = {"total": 100, "tax": 10, "line_items": []}
    result = run_matching(extracted, None, [])
    assert result.match_status == "no_po"
    assert result.po_id is None


def test_run_matching_matched():
    """run_matching with matching invoice and PO returns matched."""
    from agents.matching_erp.matching import run_matching
    from agents.matching_erp.models import PODto, POLineItem

    extracted = {
        "total": 1500.00,
        "tax": 150.00,
        "line_items": [
            {"quantity": 10, "unit_price": 50.00, "amount": 500.00},
            {"quantity": 20, "unit_price": 50.00, "amount": 1000.00},
        ],
    }
    po = PODto(
        id="po-1",
        po_number="PO-DEMO-001",
        total=1500.00,
        tax=150.00,
        line_items=[
            POLineItem(quantity=10, unit_price=50.00, amount=500.00),
            POLineItem(quantity=20, unit_price=50.00, amount=1000.00),
        ],
    )
    result = run_matching(extracted, po, [])
    assert result.match_status == "matched"
    assert result.po_id == "po-1"
    assert len(result.variances) == 0


def test_run_matching_variance():
    """run_matching with total mismatch returns variance."""
    from agents.matching_erp.matching import run_matching
    from agents.matching_erp.models import PODto

    extracted = {"total": 2000.00, "tax": 150.00, "line_items": []}
    po = PODto(id="po-1", po_number="P1", total=1500.00, tax=150.00, line_items=[])
    result = run_matching(extracted, po, [])
    assert result.match_status == "variance"
    assert any(v.type == "price" for v in result.variances)


@pytest.mark.asyncio
async def test_run_matching_erp_returns_dict():
    """run_matching_erp returns dict with match_result, vendor_validation, posting."""
    from agents.matching_erp.processor import run_matching_erp

    validated_data = {
        "extracted_data": {
            "po_number": "PO-DEMO-001",
            "supplier": "Acme Corp",
            "total": 1500.00,
            "tax": 150.00,
            "line_items": [
                {"quantity": 10, "unit_price": 50.00, "amount": 500.00},
                {"quantity": 20, "unit_price": 50.00, "amount": 1000.00},
            ],
        },
    }
    result = await run_matching_erp("job-1", validated_data)
    assert isinstance(result, dict)
    assert "match_result" in result
    assert "vendor_validation" in result
    assert "posting" in result
    assert result["match_result"]["match_status"] in ("matched", "variance", "no_po", "error")
