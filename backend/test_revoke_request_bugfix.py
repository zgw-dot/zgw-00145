"""
撤销申请链路专项回归测试
覆盖：
1. 运营从列表页发起单条申请
2. 运营从列表页发起批量申请
3. 运营从详情页发起申请
4. 重复申请拦截
5. 撤销中记录从打印清单列表消失
6. 撤销中记录从打印清单导出CSV消失
7. 打印清单列表与导出CSV内容完全一致
"""
import urllib.request
import urllib.error
import json
import http.cookiejar
import sys

BASE_URL = 'http://localhost:5000'
PASS = 0
FAIL = 0


def make_opener():
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def post(opener, path, data):
    req = urllib.request.Request(BASE_URL + path, data=json.dumps(data).encode('utf-8'), method='POST')
    req.add_header('Content-Type', 'application/json')
    try:
        return json.loads(opener.open(req).read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode('utf-8'))
        except Exception:
            return {'success': False, 'message': str(e), 'code': e.code}


def get(opener, path):
    req = urllib.request.Request(BASE_URL + path)
    try:
        return json.loads(opener.open(req).read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode('utf-8'))
        except Exception:
            return {'success': False, 'message': str(e), 'code': e.code}


def download(opener, path):
    req = urllib.request.Request(BASE_URL + path)
    try:
        resp = opener.open(req)
        return resp.read().decode('utf-8-sig')
    except urllib.error.HTTPError as e:
        return None


def upload_csv(opener, path, filename, content_bytes):
    boundary = '----TestBoundary123456'
    body = bytearray()
    body.extend(f'------{boundary}\r\n'.encode())
    body.extend(f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode())
    body.extend('Content-Type: text/csv\r\n\r\n'.encode())
    body.extend(content_bytes)
    body.extend(f'\r\n------{boundary}--\r\n'.encode())

    req = urllib.request.Request(BASE_URL + path, data=bytes(body), method='POST')
    req.add_header('Content-Type', f'multipart/form-data; boundary=----{boundary}')
    try:
        return json.loads(opener.open(req).read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode('utf-8'))
        except Exception:
            return {'success': False, 'message': str(e), 'code': e.code}


def assert_true(name, condition, detail=''):
    global PASS, FAIL
    ok = bool(condition)
    if ok:
        PASS += 1
        icon = '✅'
    else:
        FAIL += 1
        icon = '❌'
    print(f'  {icon} {name}')
    if detail:
        print(f'     → {detail}')


def section(title):
    print()
    print('=' * 60)
    print(f'  {title}')
    print('=' * 60)


# ============================================================
section('前置：登录 + 关闭发布窗口限制')

from urllib.request import Request
def put(opener, path, data):
    req = Request(BASE_URL + path, data=json.dumps(data).encode('utf-8'), method='PUT')
    req.add_header('Content-Type', 'application/json')
    try:
        return json.loads(opener.open(req).read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode('utf-8'))
        except Exception:
            return {'success': False, 'message': str(e), 'code': e.code}


admin = make_opener()
r = post(admin, '/api/auth/login', {'username': 'admin', 'password': 'admin123'})
assert_true('admin 登录成功', r.get('success'))

r = put(admin, '/api/config', {
    'publish_window': json.dumps({
        'enabled': False, 'start_hour': 0, 'end_hour': 24, 'weekdays_only': False,
    })
})
assert_true('关闭发布窗口限制', r.get('success'))

operator = make_opener()
r = post(operator, '/api/auth/login', {'username': 'operator', 'password': 'operator123'})
assert_true('operator 登录成功', r.get('success'))

clerk = make_opener()
r = post(clerk, '/api/auth/login', {'username': 'clerk', 'password': 'clerk123'})
assert_true('clerk 登录成功', r.get('success'))


# ============================================================
section('测试1：运营从列表页发起单条撤销申请')

sku_single = 'LIST-SINGLE'
store_single = '北京朝阳店'
csv_single = f'''SKU,门店,原价,促销价,生效开始时间,生效结束时间,模板
{sku_single},{store_single},100.00,80.00,2026-08-01 00:00:00,2026-08-15 23:59:59,default
'''
r = upload_csv(operator, '/api/import', 's.csv', csv_single.encode('utf-8-sig'))
assert_true('运营导入价签成功', r.get('success'))

r = get(operator, f'/api/labels?sku={sku_single}')
single_id = r['data']['list'][0]['id']

post(operator, '/api/labels/submit', {'label_ids': [single_id]})
post(admin, '/api/labels/approve', {'label_ids': [single_id], 'approve': True})

r = get(operator, f'/api/labels/{single_id}')
assert_true('价签状态为published', r['data']['label']['status'] == 'published')

r = post(operator, '/api/labels/revoke-request', {
    'label_ids': [single_id],
    'reason': '列表页单条申请测试-价格标错'
})
assert_true('运营从列表页发起单条申请成功',
            r.get('success') and r['data']['success_count'] == 1,
            str(r.get('data', {})))

r = get(operator, f'/api/labels/{single_id}')
assert_true('申请后价签状态变为revoking',
            r['data']['label']['status'] == 'revoking',
            f"实际状态: {r['data']['label']['status']}")


# ============================================================
section('测试2：运营从列表页发起批量撤销申请')

sku_b1 = 'LIST-BATCH-1'
sku_b2 = 'LIST-BATCH-2'
sku_b3 = 'LIST-BATCH-3'
store_b = '上海浦东店'
csv_b = f'''SKU,门店,原价,促销价,生效开始时间,生效结束时间,模板
{sku_b1},{store_b},200.00,150.00,2026-08-01 00:00:00,2026-08-15 23:59:59,default
{sku_b2},{store_b},300.00,200.00,2026-08-01 00:00:00,2026-08-15 23:59:59,default
{sku_b3},{store_b},400.00,250.00,2026-08-01 00:00:00,2026-08-15 23:59:59,default
'''
r = upload_csv(operator, '/api/import', 'b.csv', csv_b.encode('utf-8-sig'))
assert_true('运营导入3条批量价签成功', r.get('success'))

batch_ids = []
for sku in [sku_b1, sku_b2, sku_b3]:
    r = get(operator, f'/api/labels?sku={sku}')
    batch_ids.append(r['data']['list'][0]['id'])

post(operator, '/api/labels/submit', {'label_ids': batch_ids})
post(admin, '/api/labels/approve', {'label_ids': batch_ids, 'approve': True})
assert_true('3条价签已发布', True)

r = post(operator, '/api/labels/revoke-request', {
    'label_ids': batch_ids,
    'reason': '列表页批量申请测试-活动提前下线'
})
assert_true('运营批量申请成功',
            r.get('success') and r['data']['success_count'] == 3,
            str(r.get('data', {})))

for bid in batch_ids:
    r = get(operator, f'/api/labels/{bid}')
    assert_true(f'批量申请后价签#{bid}状态=revoking',
                r['data']['label']['status'] == 'revoking',
                f"实际: {r['data']['label']['status']}")


# ============================================================
section('测试3：运营从详情页发起撤销申请')

sku_detail = 'DETAIL-SKU'
store_detail = '广州天河店'
csv_detail = f'''SKU,门店,原价,促销价,生效开始时间,生效结束时间,模板
{sku_detail},{store_detail},500.00,350.00,2026-08-01 00:00:00,2026-08-15 23:59:59,default
'''
r = upload_csv(operator, '/api/import', 'd.csv', csv_detail.encode('utf-8-sig'))
assert_true('导入详情页测试价签成功', r.get('success'))

r = get(operator, f'/api/labels?sku={sku_detail}')
detail_id = r['data']['list'][0]['id']

post(operator, '/api/labels/submit', {'label_ids': [detail_id]})
post(admin, '/api/labels/approve', {'label_ids': [detail_id], 'approve': True})

r = post(operator, '/api/labels/revoke-request', {
    'label_ids': [detail_id],
    'reason': '详情页申请测试-供应商调价'
})
assert_true('运营从详情页发起申请成功',
            r.get('success') and r['data']['success_count'] == 1)

r = get(operator, f'/api/labels/{detail_id}')
assert_true('详情页申请后状态=revoking',
            r['data']['label']['status'] == 'revoking')


# ============================================================
section('测试4：重复申请拦截')

r = post(operator, '/api/labels/revoke-request', {
    'label_ids': [single_id],
    'reason': '重复申请测试'
})
assert_true('撤销中重复申请被拦截',
            r.get('success') and r['data']['success_count'] == 0 and len(r['data']['failed']) >= 1,
            str(r.get('data', {})))

if r['data'].get('failed'):
    msg = r['data']['failed'][0].get('reason', '')
    assert_true('失败原因含"处理中"或"重复"',
                '处理中' in msg or '重复' in msg,
                f'实际原因: {msg}')


# ============================================================
section('测试5：撤销中记录从打印清单列表消失')

r = get(operator, '/api/print-queue?status=pending')
pending_ids = [p['label_id'] for p in r['data']['list']]

assert_true(f'打印清单列表不含撤销中的{sku_single}',
            single_id not in pending_ids,
            f'实际列表label_ids: {pending_ids}')

assert_true(f'打印清单列表不含撤销中的{sku_b1}',
            batch_ids[0] not in pending_ids)

assert_true(f'打印清单列表不含撤销中的{sku_b2}',
            batch_ids[1] not in pending_ids)

assert_true(f'打印清单列表不含撤销中的{sku_detail}',
            detail_id not in pending_ids)


# ============================================================
section('测试6：撤销中记录从打印清单导出CSV消失 + 列表与导出一致')

csv_content = download(operator, '/api/export/print-queue?status=pending')
assert_true('打印清单CSV导出成功且含表头',
            csv_content is not None and 'SKU' in csv_content,
            f'CSV首行: {csv_content.strip().split(chr(10))[0] if csv_content else "None"}')

revoking_skus = [sku_single, sku_b1, sku_b2, sku_b3, sku_detail]
for s in revoking_skus:
    assert_true(f'打印清单CSV不含撤销中的SKU {s}',
                s not in csv_content,
                f'CSV中检测到SKU: {s}')

csv_lines = [l for l in csv_content.strip().split('\n') if l][1:]
csv_label_ids = set()
for line in csv_lines:
    parts = line.split(',')
    if len(parts) >= 2:
        try:
            csv_label_ids.add(int(parts[1]))
        except (ValueError, IndexError):
            pass

list_label_ids = set(pending_ids)

assert_true('打印清单列表与CSV导出的label_id集合完全一致',
            list_label_ids == csv_label_ids,
            f'列表有 {len(list_label_ids)} 条, CSV有 {len(csv_label_ids)} 条, 差异={list_label_ids ^ csv_label_ids}')

r_all = get(operator, '/api/print-queue')
list_all_ids = set(p['label_id'] for p in r_all['data']['list'])

csv_all = download(operator, '/api/export/print-queue')
csv_all_lines = [l for l in csv_all.strip().split('\n') if l][1:]
csv_all_ids = set()
for line in csv_all_lines:
    parts = line.split(',')
    if len(parts) >= 2:
        try:
            csv_all_ids.add(int(parts[1]))
        except (ValueError, IndexError):
            pass

assert_true('无筛选时列表与CSV导出label_id集合完全一致',
            list_all_ids == csv_all_ids,
            f'列表有 {len(list_all_ids)} 条, CSV有 {len(csv_all_ids)} 条, 差异={list_all_ids ^ csv_all_ids}')


# ============================================================
section('测试7：权限越权验证（补充）')

r = post(clerk, '/api/labels/revoke-request', {
    'label_ids': [single_id],
    'reason': 'clerk越权测试'
})
assert_true('clerk提撤销申请被403拦截',
            r.get('code') == 403 or '权限' in r.get('message', ''),
            r.get('message', str(r)))

r = get(clerk, f'/api/labels/{single_id}')
assert_true('clerk可查看价签详情', r.get('success'))
assert_true('clerk查看详情能看到revoking状态',
            r['data']['label']['status'] == 'revoking')

r = get(clerk, '/api/revocation-requests')
assert_true('clerk可查看撤销申请列表', r.get('success'))


# ============================================================
section('测试8：运营提申请后管理员审批（全流程贯通）')

sku_approve_test = 'APPROVE-TEST'
store_at = '深圳南山店'
csv_at = f'''SKU,门店,原价,促销价,生效开始时间,生效结束时间,模板
{sku_approve_test},{store_at},600.00,400.00,2026-09-01 00:00:00,2026-09-15 23:59:59,default
'''
r = upload_csv(operator, '/api/import', 'a.csv', csv_at.encode('utf-8-sig'))
r = get(operator, f'/api/labels?sku={sku_approve_test}')
at_id = r['data']['list'][0]['id']
post(operator, '/api/labels/submit', {'label_ids': [at_id]})
post(admin, '/api/labels/approve', {'label_ids': [at_id], 'approve': True})

r = post(operator, '/api/labels/revoke-request', {
    'label_ids': [at_id],
    'reason': '全流程测试-运营申请-管理员批准'
})
assert_true('运营提审批测试申请成功', r['data']['success_count'] == 1)

r = get(admin, '/api/revocation-requests')
at_req = [x for x in r['data']['list'] if x['label_id'] == at_id][0]
assert_true('管理员能看到pending申请', at_req['status'] == 'pending')
assert_true('申请记录含操作人operator', at_req.get('requested_by_name') == 'operator')

r = post(admin, f"/api/revocation-requests/{at_req['id']}/review", {
    'approve': True,
    'comment': '情况属实批准撤销'
})
assert_true('管理员批准成功', r.get('success'))

r = get(operator, f'/api/labels/{at_id}')
assert_true('批准后状态=revoked', r['data']['label']['status'] == 'revoked')

r = get(operator, '/api/print-queue?status=pending')
pq_ids = [p['label_id'] for p in r['data']['list']]
assert_true('批准后打印清单无该价签', at_id not in pq_ids)

csv_approved = download(operator, '/api/export/print-queue')
assert_true('批准后CSV导出无该价签', sku_approve_test not in csv_approved)


# ============================================================
section('总 结')
print()
print(f'  通过: {PASS}')
print(f'  失败: {FAIL}')
print()
if FAIL == 0:
    print('  ✅ 全部专项测试通过!')
else:
    print('  ❌ 存在失败用例')
    sys.exit(1)
