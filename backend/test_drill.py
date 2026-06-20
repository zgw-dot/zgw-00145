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
clerk_opener, _ = make_opener()

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
print('交接单演练中心自动化测试')
print('=' * 60)

# 1. 登录
print('\n--- 1. 登录准备 ---')
r = call(opener, 'POST', '/api/auth/login', {'username': 'admin', 'password': 'admin123'})
check('admin 登录', r.get('success'), r.get('message', ''))

r = call(clerk_opener, 'POST', '/api/auth/login', {'username': 'clerk', 'password': 'clerk123'})
check('clerk 登录', r.get('success'), r.get('message', ''))

# 2. 获取演练场景
print('\n--- 2. 演练场景 ---')
r = call(opener, 'GET', '/api/drill/scenarios')
check('获取演练场景列表', r.get('success'), r.get('message', ''))
check('至少有一个演练场景', isinstance(r.get('data'), list) and len(r['data']) > 0)
scenario_key = r.get('data', [{}])[0].get('key', 'handover_full_flow')
print(f'  使用场景: {scenario_key}')

# 测试前先重置演示数据，避免上次测试残留
call(opener, 'POST', '/api/drill/demo-data/drill_handover_labels/reset')

# 3. 演示数据管理
print('\n--- 3. 演示数据管理 ---')
r = call(opener, 'GET', '/api/drill/demo-data')
check('获取演示数据列表', r.get('success'), r.get('message', ''))

r = call(opener, 'POST', '/api/drill/demo-data/import', {
    'data_key': 'drill_handover_labels',
    'batch_id': 'test_batch_001',
})
check('首次导入演示数据', r.get('success'), r.get('message', ''))

r = call(opener, 'POST', '/api/drill/demo-data/import', {
    'data_key': 'drill_handover_labels',
    'batch_id': 'test_batch_001',
})
check('同一数据重复导入被拦截', not r.get('success'), r.get('message', ''))
check('拦截错误码为 DUPLICATE_DATA', r.get('code') == 'DUPLICATE_DATA')

r = call(opener, 'POST', '/api/drill/demo-data/drill_handover_labels/reset')
check('重置演示数据', r.get('success'), r.get('message', ''))

r = call(opener, 'POST', '/api/drill/demo-data/import', {
    'data_key': 'drill_handover_labels',
    'batch_id': 'test_batch_001',
})
check('重置后可重新导入', r.get('success'), r.get('message', ''))

# 4. 开始演练
print('\n--- 4. 开始演练 ---')
r = call(opener, 'POST', '/api/drill/start', {
    'scenario_key': scenario_key,
    'role': 'admin',
    'title': '自动化测试演练',
})
check('开始演练', r.get('success'), r.get('message', ''))
session_id = r.get('data', {}).get('id')
session_no = r.get('data', {}).get('session_no')
check('返回会话ID', session_id is not None)
check('返回会话编号', session_no is not None)
print(f'  会话ID: {session_id}, 编号: {session_no}')

r = call(opener, 'GET', f'/api/drill/sessions/{session_id}')
check('获取会话详情', r.get('success'), r.get('message', ''))
check('会话状态为进行中', r.get('data', {}).get('status') == 'in_progress')
check('步骤列表非空', len(r.get('data', {}).get('steps', [])) > 0)

# 5. 执行步骤
print('\n--- 5. 执行演练步骤 ---')
session_detail = r.get('data', {})
steps = session_detail.get('steps', [])
check('演练包含多个步骤', len(steps) >= 5)

first_step = steps[0]
r = call(opener, 'POST', f'/api/drill/sessions/{session_id}/steps/{first_step["step_key"]}/execute')
check('执行第一个步骤', r.get('success'), r.get('message', ''))
check('步骤状态变为 completed 或 failed', r.get('data', {}).get('step', {}).get('status') in ('completed', 'failed'))

r = call(opener, 'GET', f'/api/drill/sessions/{session_id}')
check('步骤执行后会话详情更新', r.get('success'))
updated_steps = r.get('data', {}).get('steps', [])
executed = [s for s in updated_steps if s.get('status') in ('completed', 'failed')]
check('有已执行步骤', len(executed) > 0)

# 6. 演练时间线
print('\n--- 6. 演练时间线 ---')
r = call(opener, 'GET', f'/api/drill/sessions/{session_id}/timeline')
check('获取时间线', r.get('success'), r.get('message', ''))
check('时间线包含步骤', len(r.get('data', {}).get('timeline', [])) > 0)

# 7. 演练列表
print('\n--- 7. 演练历史列表 ---')
r = call(opener, 'GET', '/api/drill/sessions?size=20')
check('获取演练列表', r.get('success'), r.get('message', ''))
check('列表非空', len(r.get('data', {}).get('list', [])) > 0)

# 8. 接口文档
print('\n--- 8. 接口文档 ---')
r = call(opener, 'GET', '/api/drill/api-docs')
check('获取接口文档', r.get('success'), r.get('message', ''))
check('文档包含多个模块', len(r.get('data', {}).keys()) > 0)

# 9. 操作清单
print('\n--- 9. 操作清单 ---')
r = call(opener, 'GET', f'/api/drill/checklist?scenario={scenario_key}')
check('获取操作清单', r.get('success'), r.get('message', ''))
check('清单包含步骤', len(r.get('data', {}).get('checklist', [])) > 0)

# 10. 权限验证
print('\n--- 10. 权限验证（越权拦截） ---')
r = call(opener, 'POST', '/api/drill/start', {
    'scenario_key': scenario_key,
    'role': 'admin',
    'title': 'admin 会话',
})
admin_session_id = r.get('data', {}).get('id')

r = call(clerk_opener, 'GET', f'/api/drill/sessions/{admin_session_id}')
check('店员不能查看管理员的演练详情（越权）', not r.get('success'))

r = call(clerk_opener, 'POST', f'/api/drill/sessions/{admin_session_id}/steps/{steps[0]["step_key"]}/execute')
check('店员不能执行管理员的演练步骤（越权）', not r.get('success'))

# 11. 重置演练
print('\n--- 11. 重置演练 ---')
r = call(opener, 'POST', f'/api/drill/sessions/{session_id}/restart')
check('重置演练', r.get('success'), r.get('message', ''))
check('重置后回到初始状态', r.get('data', {}).get('status') == 'in_progress')

r = call(opener, 'GET', f'/api/drill/sessions/{session_id}')
reset_steps = r.get('data', {}).get('steps', [])
pending_count = len([s for s in reset_steps if s.get('status') == 'pending'])
check('重置后所有步骤回到待执行', pending_count == len(reset_steps))

# 12. 完整执行一遍
print('\n--- 12. 完整流程演练 ---')
session_id2 = None
r = call(opener, 'POST', '/api/drill/start', {
    'scenario_key': scenario_key,
    'role': 'admin',
    'title': '完整流程测试',
})
if r.get('success'):
    session_id2 = r['data']['id']
    check('创建完整流程会话', True)

    all_steps = r['data'].get('steps', [])
    success_count = 0
    fail_count = 0
    for step in all_steps:
        r2 = call(opener, 'POST', f'/api/drill/sessions/{session_id2}/steps/{step["step_key"]}/execute')
        if r2.get('success'):
            success_count += 1
        else:
            fail_count += 1
            print(f'    步骤 {step["step_key"]} 失败: {r2.get("message", "")}')

    check(f'所有步骤执行成功（{success_count}/{len(all_steps)}）', fail_count == 0)

    r3 = call(opener, 'GET', f'/api/drill/sessions/{session_id2}')
    final_status = r3.get('data', {}).get('status')
    check(f'最终会话状态: {final_status}', final_status in ('completed', 'in_progress'))

    # 13. 验收记录
    print('\n--- 13. 验收记录 ---')
    acceptance = r3.get('data', {}).get('acceptance_records', [])
    check('有验收记录', len(acceptance) > 0)

    # 14. 导出验收记录
    print('\n--- 14. 导出功能 ---')
    try:
        req = urllib.request.Request(f'{BASE}/api/drill/export/acceptance/{session_id2}', method='GET')
        resp = opener.open(req)
        csv_content = resp.read().decode('utf-8')
        check('导出验收记录 CSV', '验收项' in csv_content or 'acceptance' in csv_content.lower())
        check('CSV 内容非空', len(csv_content) > 0)
    except Exception as e:
        check('导出验收记录（失败视为待验证）', False, str(e))

    try:
        req = urllib.request.Request(f'{BASE}/api/drill/export/checklist/{scenario_key}', method='GET')
        resp = opener.open(req)
        csv_content = resp.read().decode('utf-8')
        check('导出操作清单 CSV', len(csv_content) > 0)
    except Exception as e:
        check('导出操作清单（失败视为待验证）', False, str(e))

# 15. 演练记录落库验证
print('\n--- 15. 数据持久化验证 ---')
r = call(opener, 'GET', '/api/drill/sessions?size=100')
all_sessions = r.get('data', {}).get('list', [])
check('演练记录已落库（列表可查询）', len(all_sessions) >= 2)

# 16. 异常分支验证
print('\n--- 16. 异常分支验证 ---')
r = call(opener, 'POST', '/api/drill/start', {
    'scenario_key': scenario_key,
    'role': 'admin',
    'title': '异常分支测试',
})
if r.get('success'):
    sid = r['data']['id']
    all_steps = r['data'].get('steps', [])

    exception_steps = [s for s in all_steps if s.get('is_exception_branch')]
    check(f'包含异常分支步骤（{len(exception_steps)}个）', len(exception_steps) > 0)

    # 验证异常分支有正确的属性
    for step in exception_steps:
        check(f'异常分支 {step["step_key"]} 有异常说明', step.get('exception_description') is not None and len(step.get('exception_description', '')) > 0)
        check(f'异常分支 {step["step_key"]} 状态为待执行', step.get('status') == 'pending')
        check(f'异常分支 {step["step_key"]} 有预期结果', len(step.get('expected_result', '')) > 0)

# 总结
print('\n' + '=' * 60)
print(f'测试完成: 通过 {passed} 项, 失败 {failed} 项')
print('=' * 60)

if failed > 0:
    sys.exit(1)
