"""All data are synthetic fixtures; ASGI calls never bind a network socket."""
import base64
import builtins
import csv
import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from magazyn import transfers
from magazyn.store import Problem
from test_magazyn import scenario, auth, ecu, operation, post


@pytest.fixture
def setup(scenario):
    c, s, admin, worker = scenario
    headers = auth(c)
    location = s.add_location('A1')
    actor = {'id': admin, 'username': 'admin1', 'role': 'admin'}
    return c, s, headers, location, actor


def row(**changes):
    data = dict.fromkeys(transfers.IMPORT_HEADERS, '')
    data.update(format='magazyn-new-v1', kind='ecu', brand='DAF', designation='Test ECU',
                primary_number='P-100', hw='H1', sw='S1', location='A1',
                product_state='used', technical_state='working', quantity='3',
                brands_json='["MAN"]', numbers_json='[{"number":"OEM-1","number_type":"OEM"}]')
    data.update(changes)
    return data


def upload(rows, fmt='csv'):
    # Unescaped input fixtures allow testing malicious formulas independently of exporter.
    if fmt == 'csv':
        out = io.StringIO(newline='')
        writer = csv.writer(out)
        writer.writerow(transfers.IMPORT_HEADERS)
        writer.writerows([r[h] for h in transfers.IMPORT_HEADERS] for r in rows)
        raw = out.getvalue().encode('utf-8-sig')
    else:
        library = pytest.importorskip('openpyxl', reason='XLSX NOT VERIFIED: install apps/magazyn/requirements-xlsx.txt in isolated environment')
        book = library.Workbook()
        sheet = book.active
        sheet.append(list(transfers.IMPORT_HEADERS))
        for r in rows:
            sheet.append([r[h] for h in transfers.IMPORT_HEADERS])
        out = io.BytesIO()
        book.save(out)
        raw = out.getvalue()
    return dict(format=fmt, content_base64=base64.b64encode(raw).decode())


def preview(c, h, body):
    response = post(c, '/api/import/preview', body, h)
    assert response.status_code == 200, response.text
    return response.json()


def apply(c, h, body, token):
    return post(c, '/api/import/apply', dict(body, token=token), h)


@pytest.mark.parametrize('fmt', ['csv', 'xlsx'])
def test_import_preview_apply_replay_and_export(setup, fmt):
    c, s, h, loc, actor = setup
    body = upload([row()], fmt)
    result = preview(c, h, body)
    assert result['count'] == result['valid_count'] == 1 and not result['problems']
    assert s.statistics()['items'] == 0
    assert apply(c, h, body, '').status_code == 409
    imported = apply(c, h, body, result['token'])
    assert imported.status_code == 201, imported.text
    item = s.item(imported.json()['item_ids'][0])
    assert item['total'] == 3 and item['hw'] == 'H1' and item['sw'] == 'S1'
    assert len(item['numbers']) == 2
    event = s.history()[0]
    assert (event['actor_id'], event['location_code'], event['before_source'], event['after_source']) == (actor['id'], 'A1', 0, 3)
    assert event['created_at'] and event['action'] == 'receive'
    assert apply(c, h, body, result['token']).status_code == 409
    assert preview(c, h, body)['problems']
    assert s.statistics()['units'] == 3 and len(s.history()) == 1
    exported = c.get('/api/export', params={'format': fmt})
    assert exported.status_code == 200
    snapshot = dict(format=fmt, content_base64=base64.b64encode(exported.content).decode())
    assert post(c, '/api/import/preview', snapshot, h).status_code in (413, 422)


def test_csv_export_complete_filtered_and_private(setup):
    c, s, h, loc, actor = setup
    item = s.add_item(ecu(designation='Łódź ECU'), actor)
    other = s.add_location('B2')
    for location, ps, ts, quantity in [(loc,'new','working',3), (loc,'used','faulty',4), (other,'used','unknown',0)]:
        s.stock_operation(operation(item,location,action='adjust',product_state=ps,technical_state=ts,quantity=quantity), actor)
    s.add_item({'kind':'part', 'designation':'Resistor'}, actor)
    response = c.get('/api/export?format=csv&kind=ecu&brand=MAN')
    assert response.content.startswith(b'\xef\xbb\xbf')
    rows = list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))
    assert len(rows) == 3 and list(rows[0]) == list(transfers.EXPORT_HEADERS)
    assert {r['location'] for r in rows} == {'A1', 'B2'}
    assert {r['quantity'] for r in rows} == {'0', '3', '4'}
    assert rows[0]['designation'] == 'Łódź ECU'
    assert '1943-026' in rows[0]['numbers_json'] and rows[0]['hw'] == 'H1'
    assert not {'username','password_hash','actor_name','csrf'} & set(rows[0])
    assert 'admin1' not in response.text and 'scrypt' not in response.text
    assert len(list(csv.DictReader(io.StringIO(c.get('/api/export').content.decode('utf-8-sig'))))) == 4
    assert c.get('/api/export?kind=invalid').status_code == 422


@pytest.mark.parametrize('value', ['=1+1', '+SUM(A1)', '-1+1', '@SUM(A1)', ' \t\r=1', '\x00\x1f +1', '\ufeff\u200b@x'])
@pytest.mark.parametrize('fmt', ['csv', 'xlsx'])
def test_formula_injection(value, fmt):
    if fmt == 'xlsx':
        library = pytest.importorskip('openpyxl', reason='XLSX NOT VERIFIED: optional dependency absent')
    raw = transfers.encode_table(['text'], [[value]], fmt)
    if fmt == 'csv':
        cell = list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))))[1][0]
    else:
        book = library.load_workbook(io.BytesIO(raw))
        entry = book.active['A2']
        cell = entry.value
        assert entry.data_type == 's' and entry.hyperlink is None and book.vba_archive is None
        book.close()
    assert cell.startswith("'")


@pytest.mark.parametrize('second', [
    row(designation='Other', primary_number='P-200', numbers_json='[{"number":"o e m 1","number_type":"alternate"}]'),
    row(designation='Other', primary_number='OEM1', numbers_json='[]', hw='H2', sw='S2'),
    row(primary_number='P-200', numbers_json='[]', hw='H2', sw='S2'),
])
def test_duplicates_in_file_and_database_include_oem_variants(setup, second):
    c, s, h, loc, actor = setup
    duplicate = preview(c, h, upload([row(), second]))
    assert duplicate['problems'] and duplicate['token'] is None
    assert s.statistics()['items'] == 0
    body = upload([row()])
    assert apply(c, h, body, preview(c,h,body)['token']).status_code == 201
    assert preview(c, h, upload([second]))['problems']


def test_atomic_import_bad_second_row_and_revalidation(setup):
    c, s, h, loc, actor = setup
    bad = upload([row(), row(designation='Other', primary_number='P-200', numbers_json='[]', quantity='-1')])
    result = preview(c,h,bad)
    assert result['problems'] and result['token'] is None
    assert apply(c,h,bad,'').status_code == 409
    assert s.statistics()['items'] == 0 and not s.history()
    body = upload([row(), row(designation='Other', primary_number='P-200', numbers_json='[]')])
    result = preview(c,h,body)
    s.add_item({'kind':'part','designation':'Rival','primary_number':'P200'}, actor)
    assert apply(c,h,body,result['token']).status_code == 409
    assert s.statistics()['items'] == 1 and not s.history()


def test_import_rolls_back_if_write_fails(setup, monkeypatch):
    c, s, h, loc, actor = setup
    body = upload([row(), row(designation='Other', primary_number='P-200', numbers_json='[]')])
    result = preview(c,h,body)
    original = s.stock_operation
    calls = 0
    def failing(data, actor, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise Problem(409, 'Fixture failure during second write')
        return original(data,actor,**kwargs)
    monkeypatch.setattr(s, 'stock_operation', failing)
    assert apply(c,h,body,result['token']).status_code == 409
    assert s.statistics()['items'] == 0 and not s.history()


def test_zero_import_and_changed_preview_file(setup):
    c,s,h,loc,actor = setup
    body = upload([row(quantity='0')])
    token = preview(c,h,body)['token']
    assert apply(c,h,upload([row(quantity='9')]),token).status_code == 409
    assert apply(c,h,body,token).status_code == 201
    with s.connect() as con:
        assert con.execute('SELECT quantity FROM balances').fetchone()[0] == 0
    assert s.history()[0]['after_source'] == 0


def inventory_row(item, expected, quantity, ps='used', ts='working'):
    return dict(item_id=item,product_state=ps,technical_state=ts,expected_quantity=expected,quantity=quantity)


def test_inventory_zero_combinations_history_and_atomic_conflict(setup):
    c,s,h,loc,actor = setup
    item = s.add_item(ecu(), actor)
    part = s.add_item({'kind':'part','designation':'Resistor'},actor)
    s.stock_operation(operation(item,loc,quantity=5),actor)
    snapshot = c.get('/api/inventory',params={'location_id':loc}).json()
    assert len(snapshot) == 7
    assert sum(r['expected_quantity'] for r in snapshot) == 5
    body = dict(location_id=loc,rows=[inventory_row(part,0,3,'na','na'),inventory_row(item,4,0)])
    assert post(c,'/api/inventory',body,h).status_code == 409
    assert s.item(part)['total'] == 0 and s.item(item)['total'] == 5 and len(s.history()) == 1
    body['rows'][1]['expected_quantity'] = 5
    assert post(c,'/api/inventory',body,h).status_code == 200
    event = s.history()[0]
    assert (event['quantity'],event['before_source'],event['after_source'],event['actor_id'],event['location_id']) == (-5,5,0,actor['id'],loc)
    assert event['created_at'] and event['note'] == 'Inwentaryzacja'
    with s.connect() as con:
        assert con.execute('SELECT quantity FROM balances WHERE item_id=?',(item,)).fetchone()[0] == 0
    assert post(c,'/api/inventory',dict(location_id=loc,rows=[inventory_row(item,0,1)]*2),h).status_code == 422
    assert s.item(item)['total'] == 0


def test_two_concurrent_inventory_changes(setup):
    c,s,h,loc,actor = setup
    item = s.add_item(ecu(),actor)
    s.stock_operation(operation(item,loc,quantity=5),actor)
    barrier = threading.Barrier(2)
    def change(qty):
        barrier.wait()
        try:
            s.apply_inventory(loc,[inventory_row(item,5,qty)],actor)
            return 200
        except Problem as exc:
            return exc.status
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(change,[2,3])) == [200,409]
    assert s.item(item)['total'] in (2,3) and len(s.history()) == 2


def test_issue_after_inventory_read_not_overwritten(setup):
    c,s,h,loc,actor = setup
    item = s.add_item(ecu(),actor)
    s.stock_operation(operation(item,loc,quantity=5),actor)
    c.get('/api/inventory',params={'location_id':loc})
    s.stock_operation(operation(item,loc,action='issue',quantity=1,reason='sale'),actor)
    assert post(c,'/api/inventory',dict(location_id=loc,rows=[inventory_row(item,5,2)]),h).status_code == 409
    assert s.item(item)['total'] == 4


def test_authorization_csrf_and_upload_limits(setup):
    c,s,h,loc,actor = setup
    body = upload([row()])
    assert c.post('/api/import/preview',json=body).status_code == 403
    assert c.post('/api/import/apply',json=body).status_code == 403
    assert c.post('/api/inventory',json={'location_id':loc,'rows':[]}).status_code == 403
    assert post(c,'/api/import/preview',dict(format='csv',content_base64='?'),h).status_code == 422
    assert c.post('/api/import/preview',content=b'x'*(transfers.MAX_BODY+1),headers=h).status_code == 413
    worker_h = auth(c,'worker1','second-test-password-456')
    assert c.get('/api/inventory',params={'location_id':loc}).status_code == 200
    for path in ['/api/export','/api/import/template']:
        assert c.get(path).status_code == 403
    for path in ['/api/import/preview','/api/import/apply']:
        assert post(c,path,body,worker_h).status_code == 403
    assert post(c,'/api/inventory',dict(location_id=loc,rows=[inventory_row(1,0,1)]),worker_h).status_code == 403
    post(c,'/api/auth/logout',{},worker_h)
    assert c.get('/api/inventory',params={'location_id':loc}).status_code == 401
    assert c.get('/api/export').status_code == 401


def test_missing_xlsx_dependency_explicit_503(setup, monkeypatch):
    c,s,h,loc,actor = setup
    original = builtins.__import__
    def without_xlsx(name,*args,**kwargs):
        if name == 'openpyxl':
            raise ImportError('fixture: dependency absent')
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',without_xlsx)
    for path in ['/api/export?format=xlsx','/api/import/template?format=xlsx']:
        response = c.get(path)
        assert response.status_code == 503 and 'requirements-xlsx.txt' in response.text
    assert post(c,'/api/import/preview',dict(format='xlsx',content_base64=''),h).status_code == 503


def test_row_limit_headers_and_negative_quantities(setup):
    c,s,h,loc,actor = setup
    assert post(c,'/api/import/preview',upload([row()] * 1001),h).status_code == 413
    for qty in ['-1','1.5','true','2000000001']:
        assert preview(c,h,upload([row(quantity=qty)]))['problems']
    assert s.statistics()['items'] == 0


@pytest.mark.parametrize('malicious', ['formula','hyperlink','sparse'])
def test_xlsx_active_content_and_sparse_indices_rejected(setup, malicious):
    library = pytest.importorskip('openpyxl', reason='XLSX NOT VERIFIED: optional dependency absent')
    c,s,h,loc,actor = setup
    book = library.Workbook()
    sheet = book.active
    sheet.append(list(transfers.IMPORT_HEADERS))
    sheet.append([row()[h] for h in transfers.IMPORT_HEADERS])
    if malicious == 'formula':
        sheet['D2'] = '=1+1'
    elif malicious == 'hyperlink':
        sheet['D2'].hyperlink = 'https://example.invalid'
    else:
        sheet['A1048576'] = 'oversized'
    out = io.BytesIO();book.save(out)
    result = post(c,'/api/import/preview',dict(format='xlsx',content_base64=base64.b64encode(out.getvalue()).decode()),h)
    assert result.status_code in (413,422)
    assert s.statistics()['items'] == 0


def test_concurrent_import_rechecks_under_write_lock(setup):
    c,s,h,loc,actor = setup
    body = upload([row()])
    raw = transfers.decode_upload(body['content_base64'])
    secret = b'fixture-secret'
    token = transfers.import_preview(s,raw,'csv',actor,secret)['token']
    barrier = threading.Barrier(2)
    def commit(_):
        barrier.wait()
        try:
            transfers.import_apply(s,raw,'csv',actor,secret,token)
            return 201
        except Problem as exc:
            return exc.status
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(commit,range(2))) == [201,409]
    assert s.statistics()['items'] == 1 and s.statistics()['units'] == 3
    assert len(s.history()) == 1


def test_preview_expiry_and_actor_binding(setup, monkeypatch):
    c,s,h,loc,actor = setup
    raw = transfers.decode_upload(upload([row()])['content_base64'])
    secret = b'fixture-secret'
    token = transfers.import_preview(s,raw,'csv',actor,secret)['token']
    with pytest.raises(Problem) as error:
        transfers.import_apply(s,raw,'csv',dict(actor,id=actor['id']+1),secret,token)
    assert error.value.status == 409
    monkeypatch.setattr(transfers.time,'time',lambda: int(token.split('.')[0])+1)
    with pytest.raises(Problem) as error:
        transfers.import_apply(s,raw,'csv',actor,secret,token)
    assert error.value.status == 409 and s.statistics()['items'] == 0


def test_invalid_json_and_duplicate_alias_in_one_row(setup):
    c,s,h,loc,actor = setup
    for fields in [dict(numbers_json='{}'), dict(numbers_json='[{"number":7}]'),
                   dict(brands_json='null'), dict(numbers_json='not-json'),
                   dict(numbers_json='[{"number":"P100","number_type":"OEM"}]'),
                   dict(location='missing')]:
        result = preview(c,h,upload([row(**fields)]))
        assert result['problems'] and result['token'] is None
    assert s.statistics()['items'] == 0


def test_xlsx_export_balances_and_text_numbers(setup):
    library = pytest.importorskip('openpyxl', reason='XLSX NOT VERIFIED: optional dependency absent')
    c,s,h,loc,actor = setup
    item = s.add_item(ecu(primary_number='000123'),actor)
    other = s.add_location('B2')
    for place,qty in [(loc,5),(other,0)]:
        s.stock_operation(operation(item,place,action='adjust',quantity=qty),actor)
    response = c.get('/api/export?format=xlsx&brand=MAN')
    assert response.status_code == 200
    book = library.load_workbook(io.BytesIO(response.content))
    rows = list(book.active.values)
    assert rows[0] == transfers.EXPORT_HEADERS and len(rows) == 3
    index = rows[0].index('primary_number')
    assert rows[1][index] == '000123'
    assert {r[-1] for r in rows[1:]} == {0,5}
    assert all(c.data_type != 'f' and c.hyperlink is None for row in book.active for c in row)
    book.close()
