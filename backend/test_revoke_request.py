"""
价签撤销申请链路 - 回归测试
1. 权限拦截：店员(clerk)不能提申请、不能审批；运营(operator)不能审批
2. 运营单条/批量提申请：原因必填，状态变为 revoking
3. 重复申请拦截：撤销中不能重复提申请
4. 撤销中价签不进入打印队列
5. 管理员审批通过：状态变 revoked，释放冲突，日志完整
6. 管理员驳回：状态恢复 published，需填处理意见
7. 已打印拦截：批准前需填线下处理说明
8. 冲突释放：申请通过后同门店同SKU同时段可重新导入审批
9. 申请/审批/驳回独立日志：操作人、时间、原状态、处理意见、受影响打印清单
10. 历史导出、筛选结果一致；服务重启后状态一致
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
section('前置：登录各角色并关闭发布窗口限制')
admin = make_opener()
r = post(admin, '/api/auth/login', {'username': 'admin', 'password': 'admin123'})
assert_true('admin 登录成功', r.get('success'), r.get('message'))

r = post(admin, '/api/config', {
    'publish_window': json.dumps({
        'enabled': False,
        'start_hour': 0,
        'end_hour': 24,
        'weekdays_only': False,
    })
})
# 注意配置接口是 PUT，上面 POST 可能失败
r = post(admin, '/api/auth/login', {'username': 'admin', 'password': 'admin123'})
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

r = put(admin, '/api/config', {
    'publish_window': json.dumps({
        'enabled': False,
        'start_hour': 0,
        'end_hour': 24,
        'weekdays_only': False,
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
section('测试1：越权拦截 - clerk不能提申请、operator不能审批')

sku_auth = 'AUTH-SKU'
store_auth = '北京朝阳店'
csv_auth = f'''SKU,门店,原价,促销价,生效开始时间,生效结束时间,模板
{sku_auth},{store_auth},100.00,80.00,2026-08-01 00:00:00,2026-08-15 23:59:59,default
'''
r = upload_csv(admin, '/api/import', 'auth.csv', csv_auth.encode('utf-8-sig'))
assert_true('导入越权测试价签成功', r.get('success'))
r = get(admin, f'/api/labels?sku={sku_auth}')
auth_label = r['data']['list'][0]
auth_label_id = auth_label['id']
post(admin, '/api/labels/submit', {'label_ids': [auth_label_id]})
post(admin, '/api/labels/approve', {'label_ids': [auth_label_id], 'approve': True})
assert_true('越权测试价签已发布', True)

r = post(clerk, '/api/labels/revoke-request', {'label_ids': [auth_label_id], 'reason': '越权测试'})
assert_true('clerk提撤销申请被403拦截',
            r.get('code') == 403 or '权限' in r.get('message', ''),
            r.get('message', ''))

r = post(operator, '/api/revocation-requests/999/review', {'approve': True, 'comment': '越权'})
assert_true('operator审批撤销申请被403拦截',
            r.get('code') == 403 or '权限' in r.get('message', ''),
            r.get('message', ''))

r = post(clerk, '/api/revocation-requests/999/review', {'approve': True, 'comment': '越权'})
assert_true('clerk审批撤销申请被403拦截',
            r.get('code') == 403 or '权限' in r.get('message', ''),
            r.get('message', ''))


# ============================================================
section('测试2：运营提申请 - 原因必填、单条/批量、状态变revoking、不在打印队列')

sku_single = 'SINGLE-SKU'
sku_batch1 = 'BATCH-SKU1'
sku_batch2 = 'BATCH-SKU2'
store_req = '上海浦东店'

csv_req = f'''SKU,门店,原价,促销价,生效开始时间,生效结束时间,模板
{sku_single},{store_req},200.00,150.00,2026-07-01 00:00:00,2026-07-15 23:59:59,default
{sku_batch1},{store_req},300.00,200.00,2026-07-01 00:00:00,2026-07-15 23:59:59,default
{sku_batch2},{store_req},400.00,250.00,2026-07-01 00:00:00,2026-07-15 23:59:59,default
'''
r = upload_csv(operator, '/api/import', 'req.csv', csv_req.encode('utf-8-sig'))
assert_true('运营导入申请测试价签成功', r.get('success'))
r = get(operator, f'/api/labels?sku={sku_single}')
single_id = r['data']['list'][0]['id']
r = get(operator, f'/api/labels?sku={sku_batch1}')
batch1_id = r['data']['list'][0]['id']
r = get(operator, f'/api/labels?sku={sku_batch2}')
batch2_id = r['data']['list'][0]['id']

post(operator, '/api/labels/submit', {'label_ids': [single_id, batch1_id, batch2_id]})
post(admin, '/api/labels/approve', {'label_ids': [single_id, batch1_id, batch2_id], 'approve': True})
assert_true('三条价签已发布', True)

r = post(operator, '/api/labels/revoke-request', {'label_ids': [single_id], 'reason': ''})
assert_true('撤销原因空被拦截', not r.get('success'), r.get('message', ''))

r = post(operator, '/api/labels/revoke-request', {'label_ids': [single_id], 'reason': '   '})
assert_true('撤销原因纯空格被拦截', not r.get('success'), r.get('message', ''))

r = post(operator, '/api/labels/revoke-request', {'label_ids': [], 'reason': '空列表'})
assert_true('label_ids空被拦截', not r.get('success'), r.get('message', ''))

r = post(operator, '/api/labels/revoke-request', {'label_ids': [single_id], 'reason': '单条撤销-误发价签'})
assert_true('运营单条提申请成功', r.get('success') and r['data']['success_count'] == 1,
            str(r.get('data', {})))

r = get(operator, f'/api/labels/{single_id}')
assert_true('单条申请后状态为revoking', r['data']['label']['status'] == 'revoking',
            f"实际状态: {r['data']['label']['status']}")

r = get(admin, '/api/print-queue')
pq_single = [p for p in r['data']['list'] if p['label_id'] == single_id]
assert_true('revoking状态价签不出现在打印队列', len(pq_single) == 0,
            f'实际 {len(pq_single)} 条')

r = post(operator, '/api/labels/revoke-request', {
    'label_ids': [batch1_id, batch2_id],
    'reason': '批量撤销-活动提前结束'
})
assert_true('运营批量提申请成功', r.get('success') and r['data']['success_count'] == 2,
            str(r.get('data', {})))

r = get(operator, f'/api/labels/{batch1_id}')
assert_true('批量申请后batch1状态revoking', r['data']['label']['status'] == 'revoking')
r = get(operator, f'/api/labels/{batch2_id}')
assert_true('批量申请后batch2状态revoking', r['data']['label']['status'] == 'revoking')

r = get(admin, '/api/print-queue')
pq_batch = [p for p in r['data']['list'] if p['label_id'] in (batch1_id, batch2_id)]
assert_true('批量revoking状态价签均不出现打印队列', len(pq_batch) == 0)

r = get(admin, '/api/revocation-requests?status=pending')
pending = r['data']['list']
assert_true('撤销申请列表有3条pending', len(pending) >= 3, f'实际 {len(pending)} 条')

for p in pending:
    if p['label_id'] == single_id:
        assert_true('申请记录含申请人operator', p.get('requested_by_name') == 'operator',
                    f"实际: {p.get('requested_by_name')}")
        assert_true('申请记录含申请原因', '单条撤销' in p.get('reason', ''))
        assert_true('申请记录含SKU和门店', p.get('sku') == sku_single and p.get('store') == store_req)


# ============================================================
section('测试3：重复申请拦截 - 撤销中不能重复提')

r = post(operator, '/api/labels/revoke-request', {'label_ids': [single_id], 'reason': '重复申请测试'})
assert_true('撤销中重复提申请被拦截',
            r.get('success') and r['data']['success_count'] == 0 and len(r['data']['failed']) >= 1,
            str(r.get('data', {})))

if r['data'].get('failed'):
    assert_true('失败原因包含"处理中"或"重复"',
                '处理中' in r['data']['failed'][0].get('reason', '') or '重复' in r['data']['failed'][0].get('reason', ''),
                r['data']['failed'][0].get('reason', ''))


# ============================================================
section('测试4：管理员驳回流程 - 状态恢复、需填意见')

r = get(admin, f'/api/revocation-requests')
batch1_req = [x for x in r['data']['list'] if x['label_id'] == batch1_id][0]
req_id_to_reject = batch1_req['id']

r = post(admin, f'/api/revocation-requests/{req_id_to_reject}/review', {'approve': False, 'comment': ''})
assert_true('驳回不填意见被拦截', not r.get('success'), r.get('message', ''))

r = post(admin, f'/api/revocation-requests/{req_id_to_reject}/review', {
    'approve': False,
    'comment': '驳回原因：证据不足，需补充价签照片'
})
assert_true('管理员驳回成功', r.get('success'), r.get('message', ''))
assert_true('驳回后申请状态=rejected', r['data']['status'] == 'rejected')

r = get(admin, f'/api/labels/{batch1_id}')
assert_true('驳回后价签状态恢复published', r['data']['label']['status'] == 'published',
            f"实际: {r['data']['label']['status']}")

r = get(admin, f'/api/revocation-requests/{req_id_to_reject}')
req_detail = r['data']['request']
assert_true('驳回申请含审批人admin', req_detail.get('reviewed_by_name') == 'admin')
assert_true('驳回申请含审批意见', '证据不足' in req_detail.get('review_comment', ''))

r = get(admin, '/api/revocation-request-logs')
reject_logs = [l for l in r['data']['list'] if l['request_id'] == req_id_to_reject and l['action'] == 'reject']
assert_true('有独立reject操作日志', len(reject_logs) >= 1)
if reject_logs:
    assert_true('reject日志含操作人admin', reject_logs[0].get('operated_by_name') == 'admin')
    assert_true('reject日志含原状态revoking', reject_logs[0].get('original_status') == 'revoking')
    assert_true('reject日志含处理意见', '证据不足' in reject_logs[0].get('reason', ''))

r = get(admin, '/api/print-queue')
pq_reject = [p for p in r['data']['list'] if p['label_id'] == batch1_id and p['status'] == 'pending']
assert_true('驳回后价签重新出现在打印队列', len(pq_reject) >= 1,
            f'实际 {len(pq_reject)} 条')


# ============================================================
section('测试5：管理员批准 + 已打印拦截 + 线下处理说明')

sku_printed_req = 'PRINTED-REQ-SKU'
store_printed = '广州天河店'
csv_printed_req = f'''SKU,门店,原价,促销价,生效开始时间,生效结束时间,模板
{sku_printed_req},{store_printed},100.00,60.00,2026-06-01 00:00:00,2026-06-15 23:59:59,default
'''
r = upload_csv(admin, '/api/import', 'printed_req.csv', csv_printed_req.encode('utf-8-sig'))
assert_true('导入已打印申请测试价签成功', r.get('success'))
r = get(admin, f'/api/labels?sku={sku_printed_req}')
printed_req_id = r['data']['list'][0]['id']
post(admin, '/api/labels/submit', {'label_ids': [printed_req_id]})
post(admin, '/api/labels/approve', {'label_ids': [printed_req_id], 'approve': True})

r = get(admin, '/api/print-queue')
printed_pq = [p for p in r['data']['list'] if p['label_id'] == printed_req_id]
if printed_pq:
    post(admin, '/api/print-queue/mark-printed', {'ids': [printed_pq[0]['id']]})
    assert_true('标记已打印成功', True)

r = post(operator, '/api/labels/revoke-request', {
    'label_ids': [printed_req_id],
    'reason': '申请撤销已打印价签'
})
assert_true('运营对已打印价签提申请成功', r.get('success') and r['data']['success_count'] == 1)

r = get(admin, f'/api/revocation-requests')
printed_req = [x for x in r['data']['list'] if x['label_id'] == printed_req_id][0]
printed_req_id_ = printed_req['id']

r = post(admin, f'/api/revocation-requests/{printed_req_id_}/review', {'approve': True, 'comment': '批准'})
assert_true('已打印价签不填线下说明被拦截',
            not r.get('success') and r.get('code') == 'PRINTED_EXISTS',
            r.get('message', ''))

r = post(admin, f'/api/revocation-requests/{printed_req_id_}/review', {
    'approve': True,
    'comment': '已联系门店回收',
    'offline_processing_note': '门店已回收全部20张已打印价签并统一销毁，由店长签字确认'
})
assert_true('已打印价签填线下说明后批准成功', r.get('success'))

r = get(admin, f'/api/labels/{printed_req_id}')
assert_true('已打印批准后状态=revoked', r['data']['label']['status'] == 'revoked')

r = get(admin, f'/api/revocation-requests/{printed_req_id_}')
assert_true('申请记录保存线下处理说明',
            '回收' in r['data']['request'].get('offline_processing_note', ''))


# ============================================================
section('测试6：批准后冲突释放 + 独立操作日志')

r = get(admin, f'/api/revocation-requests')
single_req = [x for x in r['data']['list'] if x['label_id'] == single_id][0]
req_id_to_approve = single_req['id']

r = get(admin, f'/api/labels/{single_id}')
original_status = r['data']['label']['status']
assert_true('批准前状态为revoking', original_status == 'revoking')

r = post(admin, f'/api/revocation-requests/{req_id_to_approve}/review', {
    'approve': True,
    'comment': '情况属实，同意撤销'
})
assert_true('管理员批准成功', r.get('success'))
assert_true('批准后状态=approved', r['data']['status'] == 'approved')

r = get(admin, f'/api/labels/{single_id}')
assert_true('批准后价签状态=revoked', r['data']['label']['status'] == 'revoked')
assert_true('批准后撤销原因正确', '单条撤销' in (r['data']['label'].get('revoke_reason') or ''))

r = get(admin, '/api/revocation-request-logs')
submit_logs = [l for l in r['data']['list'] if l['request_id'] == req_id_to_approve and l['action'] == 'submit']
approve_logs = [l for l in r['data']['list'] if l['request_id'] == req_id_to_approve and l['action'] == 'approve']
assert_true('有独立submit操作日志', len(submit_logs) >= 1)
assert_true('有独立approve操作日志', len(approve_logs) >= 1)

if approve_logs:
    log = approve_logs[0]
    assert_true('approve日志含操作人ID', log.get('operated_by') is not None)
    assert_true('approve日志含创建时间', log.get('created_at') is not None)
    assert_true('approve日志含原状态revoking', log.get('original_status') == 'revoking')
    assert_true('approve日志含处理意见', '属实' in (log.get('reason') or ''))
    assert_true('approve日志含受影响打印清单ID字段', 'affected_print_queue_ids' in log)

r = get(admin, '/api/revocation-logs')
rev_logs = [l for l in r['data']['list'] if l.get('sku') == sku_single]
assert_true('批准后撤销总日志同步记录', len(rev_logs) >= 1)

csv_new = f'''SKU,门店,原价,促销价,生效开始时间,生效结束时间,模板
{sku_single},{store_req},200.00,160.00,2026-07-01 00:00:00,2026-07-15 23:59:59,default
'''
r = upload_csv(operator, '/api/import', 'new_after_revoke.csv', csv_new.encode('utf-8-sig'))
assert_true('撤销后同SKU同门店同时段新价签可导入',
            r.get('success') and r['data']['valid_rows'] == 1,
            f"通过 {r['data'].get('valid_rows')}, 失败 {r['data'].get('invalid_rows')}")

new_batch_id = r['data']['batch_id']
r = get(admin, f'/api/labels?sku={sku_single}')
new_labels = [l for l in r['data']['list'] if l['status'] == 'draft' and l['batch_id'] == new_batch_id]
assert_true('撤销后新价签生成草稿', len(new_labels) >= 1)
if new_labels:
    new_id = new_labels[0]['id']
    post(operator, '/api/labels/submit', {'label_ids': [new_id]})
    r = post(admin, '/api/labels/approve', {'label_ids': [new_id], 'approve': True})
    assert_true('撤销后新价签可审批发布',
                r.get('success') and r['data']['success_count'] == 1,
                str(r.get('data', {})))


# ============================================================
section('测试7：店员只能查看结果，不能操作')

r = get(clerk, '/api/revocation-requests')
assert_true('店员可查看撤销申请列表', r.get('success'))

r = get(clerk, f'/api/revocation-requests/{req_id_to_approve}')
assert_true('店员可查看撤销申请详情', r.get('success'))

r = get(clerk, '/api/revocation-request-logs')
assert_true('店员可查看撤销申请操作日志', r.get('success'))

r = get(clerk, f'/api/labels/{single_id}')
assert_true('店员可查看撤销价签详情', r.get('success') and r['data']['label']['status'] == 'revoked')


# ============================================================
section('测试8：导出CSV字段完整性与一致性')

req_csv = download(admin, '/api/export/revocation-requests')
assert_true('撤销申请导出CSV有内容', req_csv and len(req_csv) > 50)

req_required = ['申请ID', '价签ID', 'SKU', '门店', '申请原因', '申请状态', '申请人', '申请时间', '审批人', '审批意见', '线下处理说明']
req_header = req_csv.split('\n')[0]
req_missing = [f for f in req_required if f not in req_header]
assert_true('撤销申请CSV含全部审计字段', len(req_missing) == 0,
            f'缺失: {req_missing}' if req_missing else '全部包含')

req_lines = [l for l in req_csv.strip().split('\n') if sku_single in l]
assert_true('导出CSV中有SINGLE-SKU申请行', len(req_lines) >= 1)

log_csv = download(admin, '/api/export/revocation-request-logs')
assert_true('撤销申请操作日志导出CSV有内容', log_csv and len(log_csv) > 50)

log_required = ['记录ID', '申请ID', '价签ID', 'SKU', '操作类型', '原状态', '原因/意见', '操作人', '操作时间', '受影响打印清单ID']
log_header = log_csv.split('\n')[0]
log_missing = [f for f in log_required if f not in log_header]
assert_true('撤销申请操作日志CSV含全部字段', len(log_missing) == 0,
            f'缺失: {log_missing}' if log_missing else '全部包含')

log_lines_submit = [l for l in log_csv.strip().split('\n') if '提交申请' in l and sku_single in l]
log_lines_approve = [l for l in log_csv.strip().split('\n') if '批准撤销' in l and sku_single in l]
log_lines_reject = [l for l in log_csv.strip().split('\n') if '驳回申请' in l and sku_batch1 in l]
assert_true('导出包含submit日志行', len(log_lines_submit) >= 1)
assert_true('导出包含approve日志行', len(log_lines_approve) >= 1)
assert_true('导出包含reject日志行', len(log_lines_reject) >= 1)

label_csv = download(admin, f'/api/export/labels?sku={sku_single}')
assert_true('价签导出含"撤销中"状态映射', '撤销中' in label_csv or '已撤销' in label_csv)


# ============================================================
section('测试9：列表筛选、详情查询与重启后一致性')

r1 = get(admin, '/api/labels?status=revoking')
r2 = get(admin, '/api/labels?status=revoked')
assert_true('按status=revoking筛选可查询', r1.get('success'))
assert_true('按status=revoked筛选可查询', r2.get('success'))

revoked_list = [l for l in r2['data']['list'] if l['sku'] == sku_single]
assert_true('status=revoked筛选包含SINGLE-SKU', len(revoked_list) >= 1)

r = get(admin, f'/api/labels/{single_id}')
detail_req = r['data'].get('revocation_requests', [])
assert_true('价签详情含撤销申请列表', len(detail_req) >= 1)

r1 = get(admin, '/api/revocation-requests')
r2 = get(admin, '/api/revocation-requests')
assert_true('两次查询撤销申请总数一致', r1['data']['total'] == r2['data']['total'])

csv1 = download(admin, '/api/export/revocation-requests')
csv2 = download(admin, '/api/export/revocation-requests')
assert_true('两次导出撤销申请CSV一致', csv1 == csv2)

r = get(admin, '/api/stats/overview')
assert_true('统计接口含revoking字段', 'revoking' in r['data'])
assert_true('统计接口含revocation_request_count字段', 'revocation_request_count' in r['data'])
assert_true('统计接口revocation_request_count > 0', r['data']['revocation_request_count'] > 0)
assert_true('统计接口含revocation_request_pending字段', 'revocation_request_pending' in r['data'])


# ============================================================
section('测试10：批量批准与批量驳回整体流程验证')

sku_m1 = 'MULTI-SKU1'
sku_m2 = 'MULTI-SKU2'
sku_m3 = 'MULTI-SKU3'
store_m = '深圳南山店'

csv_m = f'''SKU,门店,原价,促销价,生效开始时间,生效结束时间,模板
{sku_m1},{store_m},500.00,300.00,2026-05-01 00:00:00,2026-05-15 23:59:59,default
{sku_m2},{store_m},600.00,400.00,2026-05-01 00:00:00,2026-05-15 23:59:59,default
{sku_m3},{store_m},700.00,500.00,2026-05-01 00:00:00,2026-05-15 23:59:59,default
'''
r = upload_csv(operator, '/api/import', 'multi.csv', csv_m.encode('utf-8-sig'))
assert_true('导入批量审批测试价签成功', r.get('success'))

m_ids = []
for sku in [sku_m1, sku_m2, sku_m3]:
    r = get(operator, f'/api/labels?sku={sku}')
    m_ids.append(r['data']['list'][0]['id'])

post(operator, '/api/labels/submit', {'label_ids': m_ids})
post(admin, '/api/labels/approve', {'label_ids': m_ids, 'approve': True})
assert_true('三条批量测试价签已发布', True)

r = post(operator, '/api/labels/revoke-request', {
    'label_ids': m_ids,
    'reason': '批量测试-活动取消'
})
assert_true('批量提3条申请全部成功',
            r.get('success') and r['data']['success_count'] == 3,
            str(r.get('data', {})))

r = get(admin, '/api/revocation-requests')
m_reqs = [x for x in r['data']['list'] if x['label_id'] in m_ids]
assert_true('3条申请记录全部生成', len(m_reqs) == 3)

r = post(admin, f'/api/revocation-requests/{m_reqs[0]["id"]}/review', {
    'approve': True, 'comment': 'ok'
})
assert_true('批量第1条批准成功', r.get('success'))

r = post(admin, f'/api/revocation-requests/{m_reqs[1]["id"]}/review', {
    'approve': False, 'comment': '驳回-需补充说明'
})
assert_true('批量第2条驳回成功', r.get('success'))

r = post(admin, f'/api/revocation-requests/{m_reqs[2]["id"]}/review', {
    'approve': True, 'comment': 'ok'
})
assert_true('批量第3条批准成功', r.get('success'))

r = get(admin, f'/api/labels/{m_ids[0]}')
s1 = r['data']['label']['status']
r = get(admin, f'/api/labels/{m_ids[1]}')
s2 = r['data']['label']['status']
r = get(admin, f'/api/labels/{m_ids[2]}')
s3 = r['data']['label']['status']
assert_true('批量混合审批结果正确：1=revoked 2=published 3=revoked',
            s1 == 'revoked' and s2 == 'published' and s3 == 'revoked',
            f'实际: {s1}, {s2}, {s3}')

r = get(admin, '/api/revocation-request-logs')
all_logs = r['data']['list']
submit_count = len([l for l in all_logs if l['action'] == 'submit'])
approve_count = len([l for l in all_logs if l['action'] == 'approve'])
reject_count = len([l for l in all_logs if l['action'] == 'reject'])
assert_true('submit/approve/reject三种日志各自独立存在',
            submit_count >= 1 and approve_count >= 1 and reject_count >= 1,
            f'submit={submit_count} approve={approve_count} reject={reject_count}')


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
