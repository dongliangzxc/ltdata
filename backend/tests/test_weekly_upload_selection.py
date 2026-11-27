"""Selected upload weeks filter source rows; they never duplicate quantities."""
import pytest
from app.services.data_period import normalize_week_selection
from app.models.schemas import RawDataRecord, UploadFileRecord, UploadConfirmJob
from tests.test_upload_cases import harness, finish_upload
from tests.test_weekly_periods import _xlsx


def prepare(h, rows, weeks, *, headers=None):
    headers = headers or ['month', 'week', 'platform', 'item_id', 'item_name', 'sales_qty', 'sales_amount', 'price']
    response = h.client.post('/api/upload/headers', files={'file': ('selected.xlsx', _xlsx(rows, headers))})
    assert response.status_code == 200
    return dict(temp_file_id=response.json()['temp_file_id'], mapping={c: c for c in headers}, ignore_columns=[],
                country_code='CN', quality_reviewed=True, period_type='week', weeks=weeks)


def rows():
    return [[202611, w, 'jd', 'same', '测试耳机', w * 10, w * 1000, 100] for w in range(1, 6)]


@pytest.mark.parametrize(('value', 'expected'), [(None, []), ([], []), ([3, '1', ' 3 ', 2], [1, 2, 3]), (['5', 1], [1, 5])])
def test_selection_normalizes_only_a_list_of_valid_local_weeks(value, expected):
    assert normalize_week_selection(value) == expected


@pytest.mark.parametrize('value', ['1,2', 1, True, [None], [0], [6], ['03'], ['3.0'], [True], [2.5]])
def test_selection_rejects_ambiguous_or_invalid_values(value):
    with pytest.raises(ValueError):
        normalize_week_selection(value)


def test_selected_weeks_keep_original_rows_amounts_metadata_and_dedup(harness):
    payload = prepare(harness, rows(), ['3', 1, 3])
    report = harness.client.post('/api/upload/validate', json=payload)
    assert report.status_code == 200, report.text
    assert (report.json()['total_rows'], report.json()['selected_rows'], report.json()['excluded_rows'], report.json()['weeks']) == (2, 2, 3, [1, 3])
    result = finish_upload(harness, harness.client.post('/api/upload/confirm', json=payload))
    assert (result['inserted'], result['skipped'], result['excluded_rows'], result['row_count']) == (2, 0, 3, 2)
    with harness.sessions() as db:
        records = db.query(RawDataRecord).order_by(RawDataRecord.week_of_month).all()
        assert [(r.week_of_month, r.sales_qty, int(r.sales_amount)) for r in records] == [(1, 10, 1000), (3, 30, 3000)]
        file = db.get(UploadFileRecord, result['file_id'])
        assert file.weeks == [1, 3] and file.row_count == 2
    repeat = finish_upload(harness, harness.client.post('/api/upload/confirm', json=prepare(harness, rows(), [1, 3])))
    assert (repeat['inserted'], repeat['skipped'], repeat['excluded_rows']) == (0, 2, 3)
    later = finish_upload(harness, harness.client.post('/api/upload/confirm', json=prepare(harness, rows(), [2, 4, 5])))
    assert later['inserted'] == 3
    with harness.sessions() as db:
        assert db.query(RawDataRecord).count() == 5
        assert sum(r.sales_qty for r in db.query(RawDataRecord)) == 150


def test_quality_warnings_and_month_range_only_include_selected_rows(harness):
    source = rows(); source[1][5] = 'invalid-number'; source[1][0] = 202610
    payload = prepare(harness, source, [1, 3])
    report = harness.client.post('/api/upload/validate', json=payload)
    assert report.status_code == 200 and report.json()['issue_count'] == 0
    assert report.json()['total_rows'] == 2
    result = finish_upload(harness, harness.client.post('/api/upload/confirm', json=payload))
    assert result['month_range'] == '202611'
    assert result['inserted'] == 2


@pytest.mark.parametrize('options', [{'weeks': [5]}, {'weeks': [1], 'period_type': 'month'}, {'weeks': [1], 'week': 1}, {'weeks': ['03']}])
def test_invalid_or_empty_selection_is_rejected_before_creating_jobs(harness, options):
    payload = prepare(harness, rows()[:2], [1]); payload.update(options)
    for endpoint in ['validate', 'confirm']:
        response = harness.client.post('/api/upload/' + endpoint, json=payload)
        assert response.status_code == 422, response.text
    with harness.sessions() as db:
        assert db.query(UploadConfirmJob).count() == db.query(UploadFileRecord).count() == db.query(RawDataRecord).count() == 0


def test_multiple_weeks_require_a_real_unignored_week_column(harness):
    headers = ['month', 'platform', 'item_id', 'item_name', 'sales_qty', 'sales_amount', 'price']
    payload = prepare(harness, [[202611, 'jd', 'one', '测试耳机', 10, 1000, 100]], [1, 2], headers=headers)
    assert harness.client.post('/api/upload/confirm', json=payload).status_code == 422
    payload = prepare(harness, rows(), [1, 3]); payload['ignore_columns'] = ['week']
    assert harness.client.post('/api/upload/confirm', json=payload).status_code == 422


def test_empty_selection_imports_all_original_weeks(harness):
    result = finish_upload(harness, harness.client.post('/api/upload/confirm', json=prepare(harness, rows(), [])))
    assert result['inserted'] == 5 and result['weeks'] == [1, 2, 3, 4, 5]
