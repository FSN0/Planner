# tests/unit/test_sync_odoo_metrics.py
from app.services.sync_service import _merge_odoo_metric, _odoo_metric_value


def test_merge_odoo_metric_sums_when_both_present():
    assert _merge_odoo_metric(1.5, 2.0) == 3.5


def test_merge_odoo_metric_keeps_existing_when_new_empty():
    assert _merge_odoo_metric(4.0, None) == 4.0
    assert _merge_odoo_metric(None, 3.0) == 3.0


def test_odoo_metric_value_parses_strings():
    assert _odoo_metric_value('2.75') == 2.75
    assert _odoo_metric_value('') is None
