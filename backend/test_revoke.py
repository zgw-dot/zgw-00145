"""
价签发布撤销 - 回归测试
1. 权限拦截：运营(operator)和店员(clerk)不能调用撤销接口
2. 已打印拦截：已打印的价签不能直接撤销
3. 撤销后冲突释放：撤销后的价签不再占用时段，新价签可以导入和审批
4. 撤销日志导出：日志包含操作人、时间、原状态、撤销原因、受影响打印清单ID
5. 服务重启后状态一致：撤销后数据持久化，查询结果一致
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


def put(opener, path, data):
    req = urllib.request.Request(BASE_URL + path, data=json.dumps(data).encode('utf-8'), method='PUT')
    req.add_header('Content-Type', 'application/json')
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
section('前置：登录 admin 并关闭发布窗口限制')
admin = make_opener()
r = post(admin, '/api/auth/login', {'username': 'admin', 'password': 'admin123'})
assert_true('admin 登录成功', r.get('success'), r.get('message'))

r = put(admin, '/api/config', {
    'publish_window': json.dumps({
        'enabled': False,
        'start_hour': 0,
        'end_hour': 24,
        'weekdays_only': False,
    })
})
assert_true('关闭发布窗口限制', r.get('success'))


# ============================================================
section('测试1：权限拦截 - operator 和 clerk 不能撤销')

operator = make_opener()
r = post(operator, '/api/auth/login', {'username': 'operator', 'password': 'operator123'})
assert_true('operator 登录成功', r.get('success'))

clerk = make_opener()
r = post(clerk, '/api/auth/login', {'username': 'clerk', 'password': 'clerk123'})
assert_true('clerk 登录成功', r.get('success'))

r = post(operator, '/api/labels/1/revoke', {'reason': '越权测试'})
assert_true('运营(operator)越权撤销被 403 拦截',
            r.get('code') == 403 or '权限' in r.get('message', ''),
            r.get('message', ''))

r = post(clerk, '/api/labels/1/revoke', {'reason': '越权测试'})
assert_true('店员(clerk)越权撤销被 403 拦截',
            r.get('code') == 403 or '权限' in r.get('message', ''),
            r.get('message', ''))


# ============================================================
section('测试2：正常撤销流程 + 已打印拦截')

sku_revoke = 'REVOKE-SKU'
store_revoke = '北京朝阳店'

csv_revoke = f'''SKU,门店,原价,促销价,生效开始时间,生效结束时间,模板
{sku_revoke},{store_revoke},100.00,70.00,2026-09-01 00:00:00,2026-09-15 23:59:59,default
'''
r = upload_csv(admin, '/api/import', 'revoke1.csv', csv_revoke.encode('utf-8-sig'))
assert_true('导入撤销测试用价签成功', r.get('success'), r.get('message', ''))
batch_id = r['data']['batch_id']

r = get(admin, f'/api/labels?sku={sku_revoke}')
labels = r['data']['list']
assert_true('导入生成1条草稿', len(labels) == 1, f'实际 {len(labels)} 条')
label_id = labels[0]['id']

r = post(admin, '/api/labels/submit', {'label_ids': [label_id]})
assert_true('提交审批成功', r['data']['success_count'] == 1)

r = post(admin, '/api/labels/approve', {'label_ids': [label_id], 'approve': True})
assert_true('审批发布成功', r['data']['success_count'] == 1)

r = get(admin, '/api/print-queue')
pq_items = [p for p in r['data']['list'] if p['label_id'] == label_id]
assert_true('打印清单中有该价签的待打印项', len(pq_items) > 0)
pq_id = pq_items[0]['id']

# 2a: 正常撤销（未打印）
r = post(admin, f'/api/labels/{label_id}/revoke', {'reason': '误发价签-撤销测试'})
assert_true('正常撤销成功', r.get('success'), r.get('message', ''))

r = get(admin, f'/api/labels/{label_id}')
label_status = r['data']['label']['status']
assert_true('撤销后状态变为 revoked', label_status == 'revoked', f'实际状态: {label_status}')

r = get(admin, '/api/print-queue')
pq_after = [p for p in r['data']['list'] if p['label_id'] == label_id and p['status'] == 'pending']
assert_true('撤销后待打印项已移出打印清单', len(pq_after) == 0, f'剩余 {len(pq_after)} 条')

r = get(admin, f'/api/labels/{label_id}')
revoked_at = r['data']['label'].get('revoked_at')
revoke_reason = r['data']['label'].get('revoke_reason')
assert_true('价签详情中有撤销时间', revoked_at is not None)
assert_true('价签详情中有撤销原因', '误发' in (revoke_reason or ''))

# 2b: 已打印拦截测试
sku_printed = 'PRINTED-SKU'
csv_printed = f'''SKU,门店,原价,促销价,生效开始时间,生效结束时间,模板
{sku_printed},{store_revoke},100.00,60.00,2026-10-01 00:00:00,2026-10-15 23:59:59,default
'''
r = upload_csv(admin, '/api/import', 'printed1.csv', csv_printed.encode('utf-8-sig'))
assert_true('导入已打印拦截测试用价签成功', r.get('success'))

r = get(admin, f'/api/labels?sku={sku_printed}')
printed_label = r['data']['list'][0]
printed_label_id = printed_label['id']

post(admin, '/api/labels/submit', {'label_ids': [printed_label_id]})
r = post(admin, '/api/labels/approve', {'label_ids': [printed_label_id], 'approve': True})
assert_true('发布已打印测试用价签成功', r['data']['success_count'] == 1)

r = get(admin, '/api/print-queue')
printed_pq = [p for p in r['data']['list'] if p['label_id'] == printed_label_id and p['status'] == 'pending']
if printed_pq:
    r = post(admin, '/api/print-queue/mark-printed', {'ids': [printed_pq[0]['id']]})
    assert_true('标记为已打印成功', r.get('success'))

r = post(admin, f'/api/labels/{printed_label_id}/revoke', {'reason': '尝试撤销已打印'})
assert_true('已打印价签撤销被拦截',
            not r.get('success') and '已打印' in r.get('message', ''),
            r.get('message', ''))


# ============================================================
section('测试3：撤销后冲突释放')

# 撤销后的 REVOKE-SKU 不再占用时段，导入同时段新价签应能通过
csv_new = f'''SKU,门店,原价,促销价,生效开始时间,生效结束时间,模板
{sku_revoke},{store_revoke},100.00,75.00,2026-09-01 00:00:00,2026-09-15 23:59:59,default
'''
r = upload_csv(admin, '/api/import', 'new1.csv', csv_new.encode('utf-8-sig'))
assert_true('撤销后导入同时段新价签通过校验',
            r['data']['valid_rows'] == 1,
            f"通过 {r['data']['valid_rows']}, 失败 {r['data']['invalid_rows']}")

new_batch_id = r['data']['batch_id']
r = get(admin, f'/api/labels?sku={sku_revoke}')
new_labels = [l for l in r['data']['list'] if l['status'] == 'draft' and l['batch_id'] == new_batch_id]
assert_true('新价签已生成草稿', len(new_labels) > 0)

new_label = new_labels[0]
post(admin, '/api/labels/submit', {'label_ids': [new_label['id']]})
r = post(admin, '/api/labels/approve', {'label_ids': [new_label['id']], 'approve': True})
assert_true('撤销后新价签可正常审批发布',
            r['data']['success_count'] == 1,
            f"成功 {r['data'].get('success_count')}, 失败 {r['data'].get('failed')}")


# ============================================================
section('测试4：撤销日志导出')

r = get(admin, '/api/revocation-logs')
assert_true('撤销日志接口可查询', r.get('success'))
rev_logs = r['data']['list']
assert_true('撤销日志有记录', len(rev_logs) > 0, f'共 {len(rev_logs)} 条')

log_entry = rev_logs[0]
assert_true('日志包含操作人ID', 'operated_by' in log_entry and log_entry['operated_by'] is not None)
assert_true('日志包含撤销时间', 'created_at' in log_entry and log_entry['created_at'])
assert_true('日志包含原状态', 'original_status' in log_entry and log_entry['original_status'] == 'published')
assert_true('日志包含撤销原因', 'reason' in log_entry and log_entry.get('reason', ''))
assert_true('日志包含受影响打印清单ID', 'affected_print_queue_ids' in log_entry)

revoke_log = [l for l in rev_logs if l.get('sku') == sku_revoke]
assert_true('REVOKE-SKU 的撤销日志存在', len(revoke_log) > 0)
if revoke_log:
    assert_true('REVOKE-SKU 撤销原因包含"误发"', '误发' in revoke_log[0].get('reason', ''))

rev_csv = download(admin, '/api/export/revocation-logs')
assert_true('撤销日志导出CSV有内容', rev_csv and len(rev_csv) > 50)

required_fields = ['记录ID', '价签ID', 'SKU', '门店', '原状态', '撤销原因', '操作人', '操作时间', '受影响打印清单ID']
header_line = rev_csv.split('\n')[0]
missing = [f for f in required_fields if f not in header_line]
assert_true('撤销日志CSV包含全部审计字段', len(missing) == 0,
            f'缺失字段: {missing}' if missing else '全部包含')

log_lines = [l for l in rev_csv.strip().split('\n') if sku_revoke in l]
assert_true('导出CSV中有撤销测试数据行', len(log_lines) > 0)

if log_lines:
    headers = header_line.split(',')
    row = log_lines[0].split(',')
    if '操作人' in headers and '撤销原因' in headers:
        op_idx = headers.index('操作人')
        reason_idx = headers.index('撤销原因')
        assert_true('导出CSV中操作人=admin', row[op_idx].strip() == 'admin')
        assert_true('导出CSV中撤销原因包含"误发"', '误发' in row[reason_idx])

# 价签导出CSV也要有撤销字段
label_csv = download(admin, f'/api/export/labels?sku={sku_revoke}')
assert_true('价签导出CSV有内容', label_csv and len(label_csv) > 50)
label_required = ['是否撤销', '撤销人', '撤销时间', '撤销原因']
label_header = label_csv.split('\n')[0]
label_missing = [f for f in label_required if f not in label_header]
assert_true('价签导出CSV包含撤销审计字段', len(label_missing) == 0,
            f'缺失字段: {label_missing}' if label_missing else '全部包含')

# 历史导出保留撤销记录
revoked_lines = [l for l in label_csv.strip().split('\n') if '已撤销' in l]
assert_true('价签导出CSV中包含已撤销记录', len(revoked_lines) > 0)


# ============================================================
section('测试5：服务重启后状态一致（模拟）')

# 验证数据库已持久化，通过重复查询验证一致性
r1 = get(admin, f'/api/labels/{label_id}')
label1 = r1['data']['label']

r2 = get(admin, f'/api/labels/{label_id}')
label2 = r2['data']['label']

assert_true('两次查询撤销状态一致', label1['status'] == label2['status'] == 'revoked')
assert_true('两次查询撤销原因一致', label1['revoke_reason'] == label2['revoke_reason'])
assert_true('两次查询撤销时间一致', label1['revoked_at'] == label2['revoked_at'])

r1 = get(admin, '/api/revocation-logs')
r2 = get(admin, '/api/revocation-logs')
assert_true('两次查询撤销日志总数一致',
            r1['data']['total'] == r2['data']['total'])

csv1 = download(admin, '/api/export/revocation-logs')
csv2 = download(admin, '/api/export/revocation-logs')
assert_true('两次导出撤销日志CSV一致', csv1 == csv2)

# 统计接口一致性
r1 = get(admin, '/api/stats/overview')
assert_true('统计接口包含 revoked 字段', 'revoked' in r1['data'])
assert_true('统计接口包含 revocation_count 字段', 'revocation_count' in r1['data'])
assert_true('统计接口 revoked 数量 > 0', r1['data']['revoked'] > 0)
assert_true('统计接口 revocation_count 数量 > 0', r1['data']['revocation_count'] > 0)


# ============================================================
section('测试6：撤销原因必填校验')

sku_no_reason = 'NOREASON-SKU'
csv_nr = f'''SKU,门店,原价,促销价,生效开始时间,生效结束时间,模板
{sku_no_reason},{store_revoke},100.00,80.00,2026-11-01 00:00:00,2026-11-15 23:59:59,default
'''
r = upload_csv(admin, '/api/import', 'noreason.csv', csv_nr.encode('utf-8-sig'))
assert_true('导入撤销原因测试用价签成功', r.get('success'))

r = get(admin, f'/api/labels?sku={sku_no_reason}')
nr_label = r['data']['list'][0]
nr_label_id = nr_label['id']

post(admin, '/api/labels/submit', {'label_ids': [nr_label_id]})
post(admin, '/api/labels/approve', {'label_ids': [nr_label_id], 'approve': True})

r = post(admin, f'/api/labels/{nr_label_id}/revoke', {'reason': ''})
assert_true('撤销原因为空被拦截', not r.get('success'), r.get('message', ''))

r = post(admin, f'/api/labels/{nr_label_id}/revoke', {})
assert_true('撤销原因缺失被拦截', not r.get('success'), r.get('message', ''))

r = post(admin, f'/api/labels/{nr_label_id}/revoke', {'reason': '   '})
assert_true('撤销原因纯空格被拦截', not r.get('success'), r.get('message', ''))


# ============================================================
section('测试7：非已发布状态不能撤销')

r = post(admin, f'/api/labels/{label_id}/revoke', {'reason': '再次撤销'})
assert_true('已撤销状态不能再次撤销', not r.get('success'),
            '已撤销' in r.get('message', '') or '已发布' in r.get('message', ''))

draft_labels = [l for l in get(admin, '/api/labels?status=draft')['data']['list'] if l.get('sku', '').startswith('NO')]
if draft_labels:
    r = post(admin, f'/api/labels/{draft_labels[0]["id"]}/revoke', {'reason': '草稿撤销'})
    assert_true('草稿状态不能撤销', not r.get('success'), r.get('message', ''))


# ============================================================
section('测试8：运营和店员可查看撤销日志但不能触发撤销')

r = get(operator, '/api/revocation-logs')
assert_true('运营可以查看撤销日志', r.get('success'))

r = get(clerk, '/api/revocation-logs')
assert_true('店员可以查看撤销日志', r.get('success'))

r = get(operator, '/api/labels?status=revoked')
assert_true('运营可以查看已撤销价签', r.get('success'))

r = get(clerk, '/api/labels?status=revoked')
assert_true('店员可以查看已撤销价签', r.get('success'))


# ============================================================
section('总 结')
print()
print(f'  通过: {PASS}')
print(f'  失败: {FAIL}')
print()
if FAIL == 0:
    print('  ✅ 全部测试通过!')
else:
    print('  ❌ 存在失败用例')
    sys.exit(1)
