import urllib.request, urllib.parse, json, http.cookiejar, sys, time

BASE = 'http://localhost:5000'

def make_opener():
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj)), cj

def call(opener, method, path, data=None):
    url = f'{BASE}{path}'
    if method == 'POST' and data is None:
        data = {}
    if data is not None:
        req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), method=method)
        req.add_header('Content-Type', 'application/json')
    else:
        req = urllib.request.Request(url, method=method)
    try:
        resp = opener.open(req)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
            return {'success': False, 'status': e.code, **body}
        except Exception:
            return {'success': False, 'status': e.code, 'message': f'HTTP {e.code}'}
    except Exception as e:
        return {'success': False, 'message': str(e)}

opener, _ = make_opener()

passed = 0
failed = 0

def check(name, condition, detail=''):
    global passed, failed
    if condition:
        passed += 1
        print(f'  ✅ {name}')
    else:
        failed += 1
        print(f'  ❌ {name} {detail}')

print('=' * 60)
print('交接单模块端到端测试')
print('=' * 60)

# 1. 登录 admin
print('\n--- 1. 登录 & 准备数据 ---')
r = call(opener, 'POST', '/api/auth/login', {'username': 'admin', 'password': 'admin123'})
check('admin 登录', r.get('success'))

r = call(opener, 'PUT', '/api/config', {'publish_window': {'enabled': False}})
check('禁用发布窗口', r.get('success'))

csv_content = '''SKU,门店,原价,促销价,生效开始时间,生效结束时间,模板
HSKU01,北京朝阳店,99.00,69.00,2026-07-01 00:00:00,2026-07-31 23:59:59,default
HSKU02,北京朝阳店,199.00,149.00,2026-07-01 00:00:00,2026-07-15 23:59:59,promotion
HSKU03,北京朝阳店,50.00,39.00,2026-08-01 00:00:00,2026-08-31 23:59:59,default
HSKU04,上海浦东店,100.00,79.00,2026-07-01 00:00:00,2026-07-31 23:59:59,default
'''

boundary = '----TestBoundary123456'
body = b''
body += f'------TestBoundary123456\r\nContent-Disposition: form-data; name="file"; filename="test_handover.csv"\r\nContent-Type: text/csv\r\n\r\n'.encode() + csv_content.encode('utf-8-sig') + b'\r\n'
body += b'------TestBoundary123456--\r\n'
req = urllib.request.Request(f'{BASE}/api/import', data=body, method='POST')
req.add_header('Content-Type', f'multipart/form-data; boundary=----TestBoundary123456')
r = json.loads(opener.open(req).read())
check('CSV 导入', r.get('success'), r.get('message', ''))

label_ids = []
r = call(opener, 'GET', '/api/labels?status=draft&size=10')
if r.get('success'):
    label_ids = [l['id'] for l in r['data']['list'][:4]]

if not label_ids:
    r = call(opener, 'GET', '/api/labels?size=10')
    if r.get('success') and r['data']['list']:
        label_ids = [l['id'] for l in r['data']['list'][:4]]

check('获取价签ID列表', len(label_ids) > 0, f'找到 {len(label_ids)} 个')

bj_labels = []
sh_labels = []
for lid in label_ids:
    r = call(opener, 'GET', f'/api/labels/{lid}')
    if r.get('success'):
        store = r['data']['label']['store']
        if '北京' in store:
            bj_labels.append(lid)
        elif '上海' in store:
            sh_labels.append(lid)

# 提交 & 审批价签
print('\n--- 2. 提交 & 审批发布价签 ---')
r = call(opener, 'POST', '/api/labels/submit', {'label_ids': label_ids})
check('提交价签', r.get('success'), r.get('message', ''))

r = call(opener, 'POST', '/api/labels/approve', {'label_ids': label_ids, 'approve': True})
check('审批发布价签', r.get('success'), r.get('message', ''))
if r.get('success') and r.get('data', {}).get('failed'):
    print(f'  ⚠️ 部分价签审批失败: {r["data"]["failed"]}')

r = call(opener, 'GET', '/api/labels?status=published&size=20')
if r.get('success'):
    published = r['data']['list']
    bj_labels = [l['id'] for l in published if '北京' in l['store']]
    sh_labels = [l['id'] for l in published if '上海' in l['store']]
    label_ids = [l['id'] for l in published]
    if not published:
        r2 = call(opener, 'GET', '/api/labels?status=pending_approval&size=20')
        if r2.get('success'):
            pending_ids = [l['id'] for l in r2['data']['list']]
            if pending_ids:
                r3 = call(opener, 'POST', '/api/labels/approve', {'label_ids': pending_ids, 'approve': True})
                r4 = call(opener, 'GET', '/api/labels?status=published&size=20')
                if r4.get('success'):
                    published = r4['data']['list']
                    bj_labels = [l['id'] for l in published if '北京' in l['store']]
                    sh_labels = [l['id'] for l in published if '上海' in l['store']]
                    label_ids = [l['id'] for l in published]

if not bj_labels:
    r = call(opener, 'GET', '/api/labels?status=published&size=20')
    if r.get('success'):
        for l in r['data']['list']:
            if '北京' in l['store'] and l['id'] not in bj_labels:
                bj_labels.append(l['id'])
            if '上海' in l['store'] and l['id'] not in sh_labels:
                sh_labels.append(l['id'])

print(f'  北京标签: {bj_labels}, 上海标签: {sh_labels}')

check('北京朝阳店已发布价签', len(bj_labels) > 0, f'{len(bj_labels)} 个')
check('上海浦东店已发布价签', len(sh_labels) > 0, f'{len(sh_labels)} 个')

# 3. 创建交接单
print('\n--- 3. 创建交接单 ---')
if bj_labels:
    r = call(opener, 'POST', '/api/handover-sheets', {
        'title': '北京朝阳店6月第一批',
        'store': '北京朝阳店',
        'remark': '测试交接单',
        'label_ids': bj_labels[:2],
    })
    check('创建北京交接单', r.get('success'), r.get('message', ''))
    if not r.get('success'):
        print(f'  ⚠️ 创建失败详情: {r}')
    sheet_id_bj = r.get('data', {}).get('sheet_id')
else:
    sheet_id_bj = None
    check('创建北京交接单', False, '无可用价签')

if sh_labels:
    r = call(opener, 'POST', '/api/handover-sheets', {
        'title': '上海浦东店6月第一批',
        'store': '上海浦东店',
        'remark': '',
        'label_ids': sh_labels[:1],
    })
    check('创建上海交接单', r.get('success'), r.get('message', ''))
    sheet_id_sh = r.get('data', {}).get('sheet_id')
else:
    sheet_id_sh = None
    check('创建上海交接单', False, '无可用价签')

# 4. 重复加单拦截
print('\n--- 4. 冲突检测: 重复加单 ---')
if bj_labels and sheet_id_bj:
    r = call(opener, 'POST', '/api/handover-sheets', {
        'title': '重复加单测试',
        'store': '北京朝阳店',
        'label_ids': bj_labels[:1],
    })
    check('重复价签被拦截', not r.get('success'), r.get('message', ''))

# 5. 重复添加同价签到同一单
print('\n--- 5. 冲突检测: 同单重复价签 ---')
if sh_labels and len(sh_labels) >= 1:
    r = call(opener, 'POST', '/api/handover-sheets', {
        'title': '重复ID测试',
        'store': '上海浦东店',
        'label_ids': [sh_labels[0], sh_labels[0]],
    })
    if r.get('success'):
        check('重复ID被拦截(failed中有记录)', r.get('data', {}).get('failed', []))
    else:
        check('重复ID被拦截(整体拒绝)', True)

# 6. 查询交接单列表
print('\n--- 6. 查询交接单列表 ---')
r = call(opener, 'GET', '/api/handover-sheets?status=pending')
check('查询待签收列表', r.get('success') and r['data']['total'] > 0, f'total={r.get("data", {}).get("total", 0)}')

r = call(opener, 'GET', '/api/handover-sheets?' + urllib.parse.urlencode({'store': '北京朝阳店'}))
check('按门店筛选', r.get('success'))

# 7. 查看交接单详情
print('\n--- 7. 查看交接单详情 ---')
if sheet_id_bj:
    r = call(opener, 'GET', f'/api/handover-sheets/{sheet_id_bj}')
    check('查看详情', r.get('success'), r.get('message', ''))
    check('详情含items', r.get('success') and len(r.get('data', {}).get('items', [])) > 0)
    check('详情含logs', r.get('success') and len(r.get('data', {}).get('logs', [])) > 0)
    check('初始无冲突', r.get('success') and not r.get('data', {}).get('has_conflict', True))
else:
    check('查看详情', False, '无sheet_id')

# 8. 检查冲突
print('\n--- 8. 检查冲突 ---')
if sheet_id_bj:
    r = call(opener, 'POST', f'/api/handover-sheets/{sheet_id_bj}/check-conflicts')
    check('检查冲突', r.get('success'))

# 9. 签收交接单
print('\n--- 9. 签收交接单 ---')
if sheet_id_sh:
    r = call(opener, 'POST', f'/api/handover-sheets/{sheet_id_sh}/sign')
    check('签收上海交接单', r.get('success'), r.get('message', ''))

    r = call(opener, 'POST', f'/api/handover-sheets/{sheet_id_sh}/sign')
    check('重复签收被拦截', not r.get('success'))
else:
    check('签收上海交接单', False, '无sheet_id')

# 10. 不同人签收拦截 (clerk尝试签收已签收的)
print('\n--- 10. 角色权限 ---')
opener2, _ = make_opener()
r = call(opener2, 'POST', '/api/auth/login', {'username': 'clerk', 'password': 'clerk123'})
check('clerk 登录', r.get('success'))

r = call(opener2, 'POST', '/api/handover-sheets', {
    'title': 'clerk不可建单',
    'store': '北京朝阳店',
    'label_ids': bj_labels[:1] if bj_labels else [],
})
check('clerk 不可创建交接单', not r.get('success') or r.get('status') == 403)

r = call(opener2, 'POST', f'/api/handover-sheets/{sheet_id_sh}/void', {'reason': 'clerk不可作废'})
check('clerk 不可作废交接单', not r.get('success'))

# 11. 撤销联动 - 标记冲突
print('\n--- 11. 撤销联动 & 冲突自动标记 ---')
if sheet_id_bj and bj_labels:
    r = call(opener, 'POST', f'/api/labels/{bj_labels[0]}/revoke', {'reason': '测试撤销联动'})
    check('撤销价签', r.get('success'), r.get('message', ''))

    r = call(opener, 'GET', f'/api/handover-sheets/{sheet_id_bj}')
    if r.get('success'):
        check('自动标记冲突', r['data'].get('has_conflict') == True)
        conflict_items = [i for i in r['data'].get('items', []) if i.get('is_conflict')]
        check('冲突项有记录', len(conflict_items) > 0, f'{len(conflict_items)} 项冲突')

        r = call(opener, 'POST', f'/api/handover-sheets/{sheet_id_bj}/sign')
        check('有冲突不可签收', not r.get('success'))
else:
    check('撤销联动', False, '无可用数据')

# 12. 作废交接单
print('\n--- 12. 作废交接单 ---')
if sheet_id_bj:
    r = call(opener, 'POST', f'/api/handover-sheets/{sheet_id_bj}/void', {'reason': '测试作废'})
    check('作废交接单', r.get('success'), r.get('message', ''))

    r = call(opener, 'POST', f'/api/handover-sheets/{sheet_id_bj}/void', {'reason': '重复作废'})
    check('重复作废被拦截', not r.get('success'))

    r = call(opener, 'POST', f'/api/handover-sheets/{sheet_id_bj}/void', {'reason': ''})
    check('空原因作废被拦截', not r.get('success'))
else:
    check('作废交接单', False, '无sheet_id')

# 13. 作废后再用旧单签收
print('\n--- 13. 作废后不可再签收 ---')
if sheet_id_bj:
    r = call(opener, 'POST', f'/api/handover-sheets/{sheet_id_bj}/sign')
    check('已作废单不可签收', not r.get('success'))

# 14. 日志查询
print('\n--- 14. 日志查询 ---')
r = call(opener, 'GET', '/api/handover-logs')
check('查询日志', r.get('success') and r['data']['total'] > 0, f'total={r.get("data", {}).get("total", 0)}')

r = call(opener, 'GET', '/api/handover-logs?action=create')
check('按操作类型筛选', r.get('success'))

if sheet_id_bj:
    r = call(opener, 'GET', f'/api/handover-logs?sheet_no=HO')
    check('按单号搜索日志', r.get('success'))

# 15. 导出测试
print('\n--- 15. 导出接口 ---')
try:
    req = urllib.request.Request(f'{BASE}/api/export/handover-sheets')
    resp = opener.open(req)
    content = resp.read().decode('utf-8')
    check('导出交接单列表CSV', '交接单号' in content)
except Exception as e:
    check('导出交接单列表CSV', False, str(e))

if sheet_id_bj:
    try:
        req = urllib.request.Request(f'{BASE}/api/export/handover-sheet/{sheet_id_bj}')
        resp = opener.open(req)
        content = resp.read().decode('utf-8')
        check('导出交接单明细CSV', 'SKU' in content or '序号' in content)
    except Exception as e:
        check('导出交接单明细CSV', False, str(e))

try:
    req = urllib.request.Request(f'{BASE}/api/export/handover-logs')
    resp = opener.open(req)
    content = resp.read().decode('utf-8')
    check('导出交接单日志CSV', '交接单号' in content or '操作类型' in content)
except Exception as e:
    check('导出交接单日志CSV', False, str(e))

# 16. 统计接口含交接单数据
print('\n--- 16. 统计接口 ---')
r = call(opener, 'GET', '/api/stats/overview')
check('统计含handover_pending', 'handover_pending' in r.get('data', {}))
check('统计含handover_signed', 'handover_signed' in r.get('data', {}))
check('统计含handover_conflict', 'handover_conflict' in r.get('data', {}))

# 17. 重启一致性(只读验证)
print('\n--- 17. 数据一致性验证 ---')
r = call(opener, 'GET', f'/api/handover-sheets/{sheet_id_bj}' if sheet_id_bj else '/api/handover-sheets')
if r.get('success') and sheet_id_bj:
    sheet_data = r['data']
    check('已作废单状态持久化', sheet_data.get('status') == 'voided')
    check('日志不丢失', len(sheet_data.get('logs', [])) >= 3, f'{len(sheet_data.get("logs", []))} 条日志')
    check('冲突标记持久化', sheet_data.get('has_conflict') == True)

if sheet_id_sh:
    r = call(opener, 'GET', f'/api/handover-sheets/{sheet_id_sh}')
    if r.get('success'):
        check('已签收单状态持久化', r['data'].get('status') == 'signed')

# Summary
print('\n' + '=' * 60)
print(f'测试完成: ✅ {passed} 通过, ❌ {failed} 失败')
print('=' * 60)

sys.exit(0 if failed == 0 else 1)
