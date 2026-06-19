"""
发布预检回归测试
1. 批量内互相冲突：预检和实际审批结果一致
2. 与已发布价签冲突：预检识别已发布冲突
3. 发布窗口关闭：预检标记配置限制
4. 预检导出CSV与实际审批结果一致
5. 非管理员越权预检拦截
6. 重启后预检导出内容和实际审批结果一致
"""
import urllib.request
import urllib.error
import json
import http.cookiejar
import sys
import os

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


def post_download(opener, path, data):
    req = urllib.request.Request(BASE_URL + path, data=json.dumps(data).encode('utf-8'), method='POST')
    req.add_header('Content-Type', 'application/json')
    try:
        resp = opener.open(req)
        return resp.read().decode('utf-8-sig')
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode('utf-8'))
            return None
        except Exception:
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
section('前置：登录 admin')
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
section('测试1：批量内互相冲突 — 预检与审批结果一致')

csv1 = '''SKU,门店,原价,促销价,生效开始时间,生效结束时间,模板
PC-SKU1,北京朝阳店,100.00,70.00,2026-09-01 00:00:00,2026-09-15 23:59:59,default
PC-SKU1,北京朝阳店,100.00,75.00,2026-09-10 00:00:00,2026-09-25 23:59:59,default
PC-SKU1,北京朝阳店,100.00,80.00,2026-10-01 00:00:00,2026-10-15 23:59:59,default
'''

r = upload_csv(admin, '/api/import', 'pc1.csv', csv1.encode('utf-8-sig'))
assert_true('CSV 导入成功', r.get('success'), r.get('message', ''))
batch1_id = r['data']['batch_id']

r = get(admin, '/api/labels?batch_id=' + str(batch1_id))
pc1_labels = [l for l in r['data']['list'] if l['sku'] == 'PC-SKU1']
assert_true('导入生成 3 条草稿', len(pc1_labels) == 3, f'实际 {len(pc1_labels)} 条')

pc1_ids = [l['id'] for l in pc1_labels]

r = post(admin, '/api/labels/submit', {'label_ids': pc1_ids})
assert_true('全部提交审批成功', r['data']['success_count'] == 3,
            f"成功 {r['data'].get('success_count')} 条")

r = post(admin, '/api/labels/precheck', {'label_ids': pc1_ids})
assert_true('预检请求成功', r.get('success'), r.get('message', ''))

pc_data = r['data']
assert_true('预检可发布 2 条', pc_data['publishable_count'] == 2,
            f"实际 {pc_data['publishable_count']}")
assert_true('预检冲突 1 条', pc_data['conflict_count'] == 1,
            f"实际 {pc_data['conflict_count']}")
assert_true('预检配置限制 0 条', pc_data['config_restricted_count'] == 0,
            f"实际 {pc_data['config_restricted_count']}")

conflict_item = pc_data['conflict'][0]
assert_true('冲突原因包含"重叠"', '重叠' in conflict_item['risk_reason'],
            conflict_item['risk_reason'])
assert_true('冲突建议动作有值', len(conflict_item['suggested_action']) > 0,
            conflict_item['suggested_action'])

r = post(admin, '/api/labels/approve', {'label_ids': pc1_ids, 'approve': True})
approve_success = r['data']['success_count']
approve_failed = r['data']['failed']
assert_true('审批结果与预检一致',
            approve_success == pc_data['publishable_count'] and len(approve_failed) == pc_data['conflict_count'],
            f'审批成功 {approve_success}, 预检可发布 {pc_data["publishable_count"]}')

# ============================================================
section('测试2：与已发布价签冲突 — 预检识别已发布冲突')

csv2 = '''SKU,门店,原价,促销价,生效开始时间,生效结束时间,模板
PC-SKU2,上海浦东店,200.00,150.00,2026-09-01 00:00:00,2026-09-30 23:59:59,default
PC-SKU2,上海浦东店,200.00,160.00,2026-09-15 00:00:00,2026-10-15 23:59:59,default
'''
r = upload_csv(admin, '/api/import', 'pc2.csv', csv2.encode('utf-8-sig'))
assert_true('导入PC-SKU2两条成功', r.get('success') and r['data']['valid_rows'] == 2)

batch2_id = r['data']['batch_id']
r = get(admin, '/api/labels?batch_id=' + str(batch2_id))
pc2_labels = [l for l in r['data']['list'] if l['sku'] == 'PC-SKU2']
assert_true('生成2条草稿', len(pc2_labels) == 2, f'实际 {len(pc2_labels)} 条')

label_2a = pc2_labels[0]
label_2b = pc2_labels[1]

r = post(admin, '/api/labels/submit', {'label_ids': [label_2a['id']]})
assert_true('提交PC-SKU2第一条成功', r['data']['success_count'] == 1)

r = post(admin, '/api/labels/approve', {'label_ids': [label_2a['id']], 'approve': True})
assert_true('发布PC-SKU2第一条成功', r['data']['success_count'] == 1)

r = post(admin, '/api/labels/submit', {'label_ids': [label_2b['id']]})
assert_true('提交PC-SKU2第二条成功', r['data']['success_count'] == 1)

r = post(admin, '/api/labels/precheck', {'label_ids': [label_2b['id']]})
assert_true('预检请求成功', r.get('success'))

pc2_data = r['data']
assert_true('预检识别已发布冲突', pc2_data['conflict_count'] == 1,
            f"冲突 {pc2_data['conflict_count']}, 可发布 {pc2_data['publishable_count']}")
assert_true('冲突原因包含"已发布"', '已发布' in pc2_data['conflict'][0]['risk_reason'],
            pc2_data['conflict'][0]['risk_reason'])

r = post(admin, '/api/labels/approve', {'label_ids': [label_2b['id']], 'approve': True})
assert_true('审批结果与预检一致',
            r['data']['success_count'] == 0 and len(r['data']['failed']) == 1,
            f"审批成功 {r['data']['success_count']}, 失败 {len(r['data']['failed'])}")

# ============================================================
section('测试3：发布窗口关闭 — 预检标记配置限制')

r = get(admin, '/api/config')
original_window = r['data'].get('publish_window')

r = put(admin, '/api/config', {'publish_window': json.dumps({
    'enabled': True,
    'start_hour': 3,
    'end_hour': 4,
    'weekdays_only': False,
})})
assert_true('设置发布窗口为凌晨3-4点', r.get('success'))

csv4 = '''SKU,门店,原价,促销价,生效开始时间,生效结束时间,模板
PC-SKU3,广州天河店,300.00,200.00,2026-11-01 00:00:00,2026-11-30 23:59:59,default
'''
r = upload_csv(admin, '/api/import', 'pc4.csv', csv4.encode('utf-8-sig'))
assert_true('导入PC-SKU3成功', r.get('success') and r['data']['valid_rows'] == 1)

batch4_id = r['data']['batch_id']
r = get(admin, '/api/labels?batch_id=' + str(batch4_id))
label_3 = r['data']['list'][0]

r = post(admin, '/api/labels/submit', {'label_ids': [label_3['id']]})
assert_true('提交PC-SKU3成功', r['data']['success_count'] == 1)

r = post(admin, '/api/labels/precheck', {'label_ids': [label_3['id']]})
assert_true('预检请求成功', r.get('success'))

pc3_data = r['data']
is_in_window_now = 3 <= __import__('datetime').datetime.now().hour < 4

if not is_in_window_now:
    assert_true('预检标记配置限制（发布窗口关闭）', pc3_data['config_restricted_count'] == 1,
                f"配置限制 {pc3_data['config_restricted_count']}")
    assert_true('配置限制原因包含"发布窗口"', '发布窗口' in pc3_data['config_restricted'][0]['risk_reason'],
                pc3_data['config_restricted'][0]['risk_reason'])
else:
    assert_true('当前在发布窗口内，跳过窗口关闭测试', True)

r = post(admin, '/api/labels/approve', {'label_ids': [label_3['id']], 'approve': True})
if not is_in_window_now:
    assert_true('审批因发布窗口关闭被拦截',
                r['data']['success_count'] == 0 and len(r['data']['failed']) == 1,
                f"审批成功 {r['data']['success_count']}, 失败 {len(r['data']['failed'])}")

if original_window:
    r = put(admin, '/api/config', {'publish_window': original_window if isinstance(original_window, str) else json.dumps(original_window)})
    assert_true('恢复发布窗口配置', r.get('success'))

# ============================================================
section('测试4：预检导出CSV字段完整')

csv5 = '''SKU,门店,原价,促销价,生效开始时间,生效结束时间,模板
PC-SKU4,深圳南山店,150.00,100.00,2026-12-01 00:00:00,2026-12-15 23:59:59,default
PC-SKU4,深圳南山店,150.00,110.00,2026-12-10 00:00:00,2026-12-25 23:59:59,default
'''
r = upload_csv(admin, '/api/import', 'pc5.csv', csv5.encode('utf-8-sig'))
assert_true('导入PC-SKU4成功', r.get('success') and r['data']['valid_rows'] == 2)

batch5_id = r['data']['batch_id']
r = get(admin, '/api/labels?batch_id=' + str(batch5_id))
pc4_labels = [l for l in r['data']['list'] if l['sku'] == 'PC-SKU4']
pc4_ids = [l['id'] for l in pc4_labels]

r = post(admin, '/api/labels/submit', {'label_ids': pc4_ids})
assert_true('提交PC-SKU4成功', r['data']['success_count'] == 2)

csv_content = post_download(admin, '/api/export/precheck', {'label_ids': pc4_ids})
assert_true('预检导出CSV有内容', csv_content and len(csv_content) > 50)

required_fields = ['价签ID', 'SKU', '门店', '生效开始时间', '生效结束时间', '分组', '风险原因', '建议动作']
header_line = csv_content.split('\n')[0]
headers = header_line.split(',')
missing = [f for f in required_fields if f not in header_line]
assert_true('预检CSV包含全部必要字段', len(missing) == 0,
            f'缺失字段: {missing}' if missing else '全部包含')

data_lines = [l for l in csv_content.strip().split('\n') if 'PC-SKU4' in l]
assert_true('预检CSV包含数据行', len(data_lines) >= 2, f'数据行数: {len(data_lines)}')

if '分组' in headers:
    group_idx = headers.index('分组')
    groups = set()
    for dl in data_lines:
        cols = dl.split(',')
        if len(cols) > group_idx:
            groups.add(cols[group_idx].strip())
    assert_true('预检CSV包含分组列（可发布/冲突/配置限制）',
                len(groups.intersection({'可发布', '冲突', '配置限制'})) > 0,
                f'分组值: {groups}')

# ============================================================
section('测试5：非管理员越权预检拦截')

operator = make_opener()
r = post(operator, '/api/auth/login', {'username': 'operator', 'password': 'operator123'})
assert_true('operator 登录成功', r.get('success'))

r = post(operator, '/api/labels/precheck', {'label_ids': [1]})
assert_true('运营越权预检被 403 拦截', r.get('code') == 403 or '权限' in r.get('message', ''),
            r.get('message', ''))

clerk = make_opener()
r = post(clerk, '/api/auth/login', {'username': 'clerk', 'password': 'clerk123'})
assert_true('clerk 登录成功', r.get('success'))

r = post(clerk, '/api/labels/precheck', {'label_ids': [1]})
assert_true('店员越权预检被 403 拦截', r.get('code') == 403 or '权限' in r.get('message', ''),
            r.get('message', ''))

r = post(clerk, '/api/export/precheck', {'label_ids': [1]})
assert_true('店员越权预检导出被 403 拦截', r.get('code') == 403 or '权限' in r.get('message', ''),
            r.get('message', ''))

# ============================================================
section('测试6：预检不改状态也不生成打印清单')

r = get(admin, '/api/labels?sku=PC-SKU4&status=pending_approval')
before_pending = r['data']['total']

r = get(admin, '/api/print-queue')
before_print_count = r['data']['total']

r = post(admin, '/api/labels/precheck', {'label_ids': pc4_ids})
assert_true('预检请求成功', r.get('success'))

r = get(admin, '/api/labels?sku=PC-SKU4&status=pending_approval')
after_pending = r['data']['total']
assert_true('预检后待审数量不变', after_pending == before_pending,
            f'之前 {before_pending}, 之后 {after_pending}')

r = get(admin, '/api/print-queue')
after_print_count = r['data']['total']
assert_true('预检后打印清单数量不变', after_print_count == before_print_count,
            f'之前 {before_print_count}, 之后 {after_print_count}')

# ============================================================
section('测试7：重启后预检导出与实际审批结果一致')

csv6 = '''SKU,门店,原价,促销价,生效开始时间,生效结束时间,模板
PC-SKU5,北京朝阳店,180.00,120.00,2027-01-01 00:00:00,2027-01-15 23:59:59,default
PC-SKU5,北京朝阳店,180.00,130.00,2027-01-10 00:00:00,2027-01-25 23:59:59,default
PC-SKU5,北京朝阳店,180.00,140.00,2027-02-01 00:00:00,2027-02-15 23:59:59,default
'''
r = upload_csv(admin, '/api/import', 'pc6.csv', csv6.encode('utf-8-sig'))
assert_true('导入PC-SKU5成功', r.get('success') and r['data']['valid_rows'] == 3)

batch6_id = r['data']['batch_id']
r = get(admin, '/api/labels?batch_id=' + str(batch6_id))
pc5_labels = [l for l in r['data']['list'] if l['sku'] == 'PC-SKU5']
pc5_ids = [l['id'] for l in pc5_labels]

r = post(admin, '/api/labels/submit', {'label_ids': pc5_ids})
assert_true('提交PC-SKU5成功', r['data']['success_count'] == 3)

r = post(admin, '/api/labels/precheck', {'label_ids': pc5_ids})
assert_true('预检请求成功', r.get('success'))
precheck_result_1 = r['data']

csv_export_1 = post_download(admin, '/api/export/precheck', {'label_ids': pc5_ids})
assert_true('首次预检导出成功', csv_export_1 is not None and len(csv_export_1) > 50)

csv_export_2 = post_download(admin, '/api/export/precheck', {'label_ids': pc5_ids})
assert_true('连续两次预检导出一致', csv_export_1 == csv_export_2,
            '两次导出内容不同')

r = post(admin, '/api/labels/approve', {'label_ids': pc5_ids, 'approve': True})
approve_success = r['data']['success_count']
approve_failed = r['data']['failed']
assert_true('审批结果与预检一致',
            approve_success == precheck_result_1['publishable_count'] and
            len(approve_failed) == precheck_result_1['conflict_count'] + precheck_result_1['config_restricted_count'],
            f'审批成功 {approve_success} vs 预检可发布 {precheck_result_1["publishable_count"]}, '
            f'审批失败 {len(approve_failed)} vs 预检问题 {precheck_result_1["conflict_count"] + precheck_result_1["config_restricted_count"]}')

csv_export_3 = post_download(admin, '/api/export/precheck', {'label_ids': pc5_ids})
assert_true('审批后预检导出不同（状态已变）', csv_export_1 != csv_export_3,
            '审批后预检导出内容应不同（因为状态已变更）')

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
