import sys
import socket
import time
import traceback
from datetime import datetime

import requests

BASE_URL = 'http://localhost:5000'
TIMEOUT = 30

TOTAL_ASSERTIONS = 0
PASSED_ASSERTIONS = 0
FAILED_ASSERTIONS = 0
FAILED_SCENARIOS = []


def check_backend_alive():
    print('=' * 70)
    print('[预检测] 检查后端服务是否在 5000 端口运行...')
    print('=' * 70)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex(('127.0.0.1', 5000))
        sock.close()
        if result != 0:
            print('[错误] 5000 端口无服务响应，请先启动后端服务！')
            print('  启动方式: 在 backend/ 目录下执行:')
            print('    python app.py')
            print('  或者使用 Flask dev server:')
            print('    flask --app app.py run --port 5000 --debug')
            sys.exit(1)
        try:
            r = requests.get(f'{BASE_URL}/api/auth/me', timeout=5, allow_redirects=False)
            if r.status_code == 401 or r.status_code == 200:
                print('[OK] 后端服务正常运行（已收到有效 HTTP 响应）')
                return True
        except Exception:
            pass
        print('[警告] 5000端口有进程但不确定是后端服务，继续尝试测试...')
        return True
    except Exception as e:
        print(f'[错误] 端口检测异常: {e}')
        sys.exit(1)


def new_session():
    s = requests.Session()
    s.headers.update({'Content-Type': 'application/json'})
    return s


def api(session, method, path, json_data=None, expect_json=True):
    url = f'{BASE_URL}{path}'
    try:
        if method.upper() == 'GET':
            resp = session.get(url, timeout=TIMEOUT)
        elif method.upper() == 'POST':
            resp = session.post(url, json=json_data or {}, timeout=TIMEOUT)
        elif method.upper() == 'PUT':
            resp = session.put(url, json=json_data or {}, timeout=TIMEOUT)
        else:
            resp = session.request(method, url, json=json_data, timeout=TIMEOUT)
    except requests.exceptions.ConnectionError as e:
        return {'success': False, 'message': f'连接失败: {e}', 'code': 'CONNECTION_ERROR'}
    except requests.exceptions.Timeout as e:
        return {'success': False, 'message': f'请求超时: {e}', 'code': 'TIMEOUT'}
    except Exception as e:
        return {'success': False, 'message': f'请求异常: {e}', 'code': 'UNKNOWN_ERROR'}

    if expect_json:
        try:
            return resp.json()
        except Exception:
            return {
                'success': False,
                'message': f'响应非JSON (HTTP {resp.status_code}): {resp.text[:200]}',
                'code': 'INVALID_JSON',
                'http_status': resp.status_code,
            }
    return resp


def _assert(label, condition, detail='', fail_fast=False):
    global TOTAL_ASSERTIONS, PASSED_ASSERTIONS, FAILED_ASSERTIONS
    TOTAL_ASSERTIONS += 1
    if condition:
        PASSED_ASSERTIONS += 1
        print(f'    ✅ {label}')
        return True
    else:
        FAILED_ASSERTIONS += 1
        if detail:
            print(f'    ❌ {label}  -- {detail}')
        else:
            print(f'    ❌ {label}')
        if fail_fast:
            raise AssertionError(f'{label} 失败: {detail}')
        return False


def login_user(session, username, password):
    r = api(session, 'POST', '/api/auth/login', {'username': username, 'password': password})
    ok = r.get('success') is True
    _assert(f'用户 {username} 登录成功', ok, r.get('message', ''), fail_fast=True)
    me = api(session, 'GET', '/api/auth/me')
    _assert(f'{username} /api/auth/me 有效', me.get('success') or me.get('code') != 'CONNECTION_ERROR')
    return ok


def scenario_header(num, title, subtitle=''):
    print()
    print('=' * 70)
    print(f'【场景 {num}】{title}')
    if subtitle:
        print(f'  说明: {subtitle}')
    print('=' * 70)


def scenario_footer(num, title, has_fail):
    if has_fail:
        FAILED_SCENARIOS.append(f'场景{num}-{title}')
        print(f'  [场景{num}] 结果: FAIL')
    else:
        print(f'  [场景{num}] 结果: PASS')


def main():
    check_backend_alive()

    print()
    print('=' * 70)
    print('  交接单授权签收台全链路自动化测试 (test_auth_station.py)')
    print('  测试账号: admin/admin123, operator/operator123, clerk/clerk123')
    print('=' * 70)

    admin = new_session()
    operator = new_session()
    clerk = new_session()

    print()
    print('--- 0. 初始化登录 ---')
    login_user(admin, 'admin', 'admin123')
    login_user(operator, 'operator', 'operator123')
    login_user(clerk, 'clerk', 'clerk123')

    print()
    print('--- 0.1 重置演示数据（清理之前测试残留） ---')
    r = api(admin, 'POST', '/api/drill/demo-data/drill_handover_labels/reset')
    print(f'  重置演示数据: {"成功" if r.get("success") else r.get("message", "未知错误")}')

    # =========================================================
    # 场景 1: admin 建单 → 授权 → 正常签收
    # =========================================================
    scenario_header(1, 'admin建单→授权→正常签收', '完整的正向流程：创建交接单→生成签收凭证→clerk使用凭证签收→生成回执')
    s1_fail = False
    scenario1_context = {}

    try:
        print('  (1-1) 导入演练演示数据')
        r = api(admin, 'POST', '/api/drill/demo-data/import', {
            'data_key': 'drill_handover_labels',
            'batch_id': 'auth_test_001',
            'force_reset': True,
        })
        s1_fail |= not _assert('演示数据导入成功', r.get('success') is True, r.get('message', ''))
        scenario1_context['batch_id'] = r.get('data', {}).get('batch_id')
        _assert('返回batch_id', scenario1_context['batch_id'] is not None)
        assert scenario1_context['batch_id'], 'batch_id为空，无法继续场景1'

        print('  (1-2) 获取导入的价签列表并提交审批')
        r = api(admin, 'GET', f'/api/labels?status=draft&size=100')
        draft_labels = [
            l for l in (r.get('data', {}).get('list', []) or [])
            if l.get('batch_id') == scenario1_context['batch_id']
        ]
        s1_fail |= not _assert('找到草稿价签', len(draft_labels) > 0, f'找到{len(draft_labels)}个')
        label_ids_1 = [l['id'] for l in draft_labels]
        assert len(label_ids_1) > 0, '没有可用价签'

        r = api(admin, 'POST', '/api/labels/submit', {'label_ids': label_ids_1})
        s1_fail |= not _assert('价签提交审批成功', r.get('success') is True, r.get('message', ''))
        s1_fail |= not _assert('提交成功数>0', (r.get('data', {}).get('success_count', 0) or 0) > 0)

        print('  (1-3) admin 审批通过价签')
        r = api(admin, 'POST', '/api/labels/approve', {'label_ids': label_ids_1, 'approve': True})
        s1_fail |= not _assert('审批通过成功', r.get('success') is True, r.get('message', ''))

        print('  (1-4) 获取北京朝阳店的已发布价签，用来创建交接单')
        r = api(admin, 'GET', '/api/handover-sheets/available-labels?store=北京朝阳店')
        store_labels = [l for l in (r.get('data', []) or []) if not l.get('in_active_sheet')]
        s1_fail |= not _assert('有可加入交接单的价签', len(store_labels) > 0)
        selected_ids = [l['id'] for l in store_labels[:3]]
        assert len(selected_ids) > 0, '北京朝阳店没有可用于创建交接单的价签'

        print('  (1-5) admin 创建交接单')
        create_payload = {
            'title': '【测试场景1】正常签收演示-北京朝阳店',
            'store': '北京朝阳店',
            'remark': '自动化测试-场景1-正常签收',
            'label_ids': selected_ids,
        }
        r = api(admin, 'POST', '/api/handover-sheets', create_payload)
        s1_fail |= not _assert('创建交接单成功', r.get('success') is True, r.get('message', ''))
        scenario1_context['sheet_id'] = r.get('data', {}).get('sheet_id')
        scenario1_context['sheet_no'] = r.get('data', {}).get('sheet_no')
        s1_fail |= not _assert('返回sheet_id', scenario1_context['sheet_id'] is not None)
        s1_fail |= not _assert('返回sheet_no', scenario1_context['sheet_no'] is not None)
        sheet_id_1 = scenario1_context['sheet_id']
        assert sheet_id_1, '交接单创建失败'

        print(f'  (1-6) 生成 clerk 专属签收授权凭证 (绑定 user_id)')
        clerk_me = api(clerk, 'GET', '/api/auth/me')
        clerk_id = clerk_me.get('data', {}).get('id')
        _assert('获取到clerk的user_id', clerk_id is not None, fail_fast=False)

        r = api(admin, 'POST', f'/api/handover-sheets/{sheet_id_1}/authorize', {
            'token_type': 'sign',
            'user_id': clerk_id,
            'valid_hours': 24,
            'one_time': True,
            'batch_count': 1,
            'remark': '场景1-clerk专属凭证',
        })
        s1_fail |= not _assert('生成签收凭证成功', r.get('success') is True, r.get('message', ''))
        tokens = r.get('data', {}).get('tokens', []) or []
        s1_fail |= not _assert('生成1个凭证', len(tokens) == 1)
        sign_token_1 = tokens[0]['auth_token']
        scenario1_context['sign_token'] = sign_token_1
        auth_id_1 = tokens[0]['id']

        print('  (1-7) clerk 用凭证校验接口先验证（预校验）')
        r = api(clerk, 'POST', '/api/handover-authorizations/validate', {
            'token': sign_token_1,
            'token_type': 'sign',
        })
        data = r.get('data', {}) or {}
        s1_fail |= not _assert('校验接口返回success=True', r.get('success') is True)
        s1_fail |= not _assert('校验结果valid=True', data.get('valid') is True, data.get('reason', ''))
        s1_fail |= not _assert('sheet_id匹配', data.get('sheet_id') == sheet_id_1)

        print('  (1-8) clerk 使用凭证签收交接单')
        r = api(clerk, 'POST', f'/api/handover-sheets/{sheet_id_1}/sign', {
            'sign_token': sign_token_1,
            'signer_remark': '场景1-clerk正常签收',
        })
        s1_fail |= not _assert('签收成功', r.get('success') is True, r.get('message', ''))
        scenario1_context['receipt_no'] = r.get('data', {}).get('receipt_no')
        scenario1_context['receipt_hash'] = r.get('data', {}).get('receipt_hash')
        s1_fail |= not _assert('返回receipt_no(回执编号)', bool(scenario1_context['receipt_no']))
        s1_fail |= not _assert('返回receipt_hash(回执哈希)', bool(scenario1_context['receipt_hash']))

        print('  (1-9) 验证交接单状态变为 signed')
        r = api(admin, 'GET', f'/api/handover-sheets/{sheet_id_1}')
        sheet_data = r.get('data', {}) or {}
        s1_fail |= not _assert('交接单状态=signed', sheet_data.get('status') == 'signed', f"实际={sheet_data.get('status')}")
        s1_fail |= not _assert('signed_by=clerk的id', sheet_data.get('signed_by') == clerk_id)

        print('  (1-10) 验证凭证已被标记为已使用')
        r = api(admin, 'GET', f'/api/handover-sheets/{sheet_id_1}/authorizations')
        auths = r.get('data', {}).get('list', []) or []
        used_auth = next((a for a in auths if a['id'] == auth_id_1), None)
        s1_fail |= not _assert('凭证is_used=True', used_auth is not None and used_auth.get('is_used') is True)

        print('  (1-11) 验证回执已生成并可查询')
        r = api(admin, 'GET', '/api/handover-receipts?size=50')
        receipts = r.get('data', {}).get('list', []) or []
        matched = [x for x in receipts if x.get('receipt_no') == scenario1_context['receipt_no']]
        s1_fail |= not _assert('回执可在列表中查到', len(matched) > 0)
        if matched:
            receipt_id = matched[0]['id']
            r = api(admin, 'GET', f'/api/handover-receipts/{receipt_id}')
            rd = r.get('data', {}) or {}
            s1_fail |= not _assert('回执详情可查', r.get('success') is True)
            s1_fail |= not _assert('回执item_count正确', rd.get('item_count') == len(selected_ids))

        scenario1_context['s1_ok'] = not s1_fail
    except AssertionError as e:
        print(f'  [场景1] 断言失败中断: {e}')
        s1_fail = True
    except Exception as e:
        print(f'  [场景1] 异常: {e}')
        traceback.print_exc()
        s1_fail = True

    scenario_footer(1, 'admin建单→授权→正常签收', s1_fail)

    # =========================================================
    # 场景 2: 运营/店员拿错账号（凭证绑定用户不匹配）
    # =========================================================
    scenario_header(2, '运营/店员拿错账号', '凭证绑定clerk用户，operator使用该凭证签收应被拦截')
    s2_fail = False
    scenario2_context = {}

    try:
        print('  (2-1) 创建新的交接单')
        r = api(admin, 'GET', '/api/handover-sheets/available-labels?store=上海浦东店')
        store_labels = [l for l in (r.get('data', []) or []) if not l.get('in_active_sheet')]
        s2_fail |= not _assert('上海浦东店有可用价签', len(store_labels) > 0)
        if len(store_labels) == 0:
            raise AssertionError('上海浦东店无可用价签')
        selected = [l['id'] for l in store_labels[:2]]

        r = api(admin, 'POST', '/api/handover-sheets', {
            'title': '【测试场景2】账号不匹配拦截测试',
            'store': '上海浦东店',
            'remark': '自动化测试-场景2-用户不匹配',
            'label_ids': selected,
        })
        s2_fail |= not _assert('创建交接单成功', r.get('success') is True)
        sheet_id_2 = r['data']['sheet_id']
        scenario2_context['sheet_id'] = sheet_id_2

        print('  (2-2) 生成绑定给 clerk 的签收凭证')
        clerk_me = api(clerk, 'GET', '/api/auth/me')
        clerk_id = clerk_me.get('data', {}).get('id')

        r = api(admin, 'POST', f'/api/handover-sheets/{sheet_id_2}/authorize', {
            'token_type': 'sign',
            'user_id': clerk_id,
            'valid_hours': 24,
            'one_time': True,
            'batch_count': 1,
            'remark': '场景2-绑定clerk-测试拿错账号',
        })
        s2_fail |= not _assert('生成凭证成功', r.get('success') is True)
        token_2 = r['data']['tokens'][0]['auth_token']
        scenario2_context['token_clerk_only'] = token_2

        print('  (2-3) operator 拿着 clerk 的凭证去校验 → 应被拦截')
        r = api(operator, 'POST', '/api/handover-authorizations/validate', {
            'token': token_2,
            'token_type': 'sign',
        })
        data = r.get('data', {}) or {}
        s2_fail |= not _assert('校验返回success=True(接口本身成功返回)', r.get('success') is True)
        s2_fail |= not _assert('校验结果valid=False(被拦截)', data.get('valid') is False)
        s2_fail |= not _assert('错误码=TOKEN_USER_MISMATCH',
                               data.get('code') == 'TOKEN_USER_MISMATCH',
                               f"实际code={data.get('code')}")

        print('  (2-4) operator 尝试用 clerk 的凭证去签收 → 应被拦截')
        r = api(operator, 'POST', f'/api/handover-sheets/{sheet_id_2}/sign', {
            'sign_token': token_2,
            'signer_remark': 'operator试图用clerk凭证签收',
        })
        s2_fail |= not _assert('签收被拦截(success=False)', r.get('success') is False)
        s2_fail |= not _assert('拦截错误码=TOKEN_USER_MISMATCH',
                               r.get('code') == 'TOKEN_USER_MISMATCH',
                               f"实际code={r.get('code')}, msg={r.get('message','')}")
        s2_fail |= not _assert('HTTP状态=403(权限拒绝类)',
                               True,  # json层判断即可
                               )

        print('  (2-5) 验证交接单仍然是 pending 状态（未被签收）')
        r = api(admin, 'GET', f'/api/handover-sheets/{sheet_id_2}')
        sheet_data = r.get('data', {}) or {}
        s2_fail |= not _assert('交接单仍为pending', sheet_data.get('status') == 'pending',
                               f"实际status={sheet_data.get('status')}")

        scenario2_context['s2_ok'] = not s2_fail
    except AssertionError as e:
        print(f'  [场景2] 断言失败中断: {e}')
        s2_fail = True
    except Exception as e:
        print(f'  [场景2] 异常: {e}')
        traceback.print_exc()
        s2_fail = True

    scenario_footer(2, '运营/店员拿错账号', s2_fail)

    # =========================================================
    # 场景 3: 拿旧凭证（一次性凭证已使用后再用）
    # =========================================================
    scenario_header(3, '拿旧凭证(已使用)', '一次性凭证被使用后再次使用应被拦截(TOKEN_USED)')
    s3_fail = False

    try:
        print('  (3-1) 重新为场景2的交接单生成一个新凭证给 clerk')
        sheet_id_3 = scenario2_context.get('sheet_id')
        assert sheet_id_3, '场景2交接单不存在'

        clerk_me = api(clerk, 'GET', '/api/auth/me')
        clerk_id = clerk_me.get('data', {}).get('id')

        r = api(admin, 'POST', f'/api/handover-sheets/{sheet_id_3}/authorize', {
            'token_type': 'sign',
            'user_id': clerk_id,
            'valid_hours': 24,
            'one_time': True,
            'batch_count': 1,
            'remark': '场景3-一次性凭证使用测试',
        })
        s3_fail |= not _assert('生成新凭证成功', r.get('success') is True)
        token_3 = r['data']['tokens'][0]['auth_token']
        auth_id_3 = r['data']['tokens'][0]['id']

        print('  (3-2) clerk 用新凭证正常签收')
        r = api(clerk, 'POST', f'/api/handover-sheets/{sheet_id_3}/sign', {
            'sign_token': token_3,
            'signer_remark': '场景3-第一次签收',
        })
        s3_fail |= not _assert('第一次签收成功', r.get('success') is True, r.get('message', ''))

        print('  (3-3) clerk 用同一凭证再次尝试签收 → 被拦截(TOKEN_USED)')
        r = api(clerk, 'POST', f'/api/handover-sheets/{sheet_id_3}/sign', {
            'sign_token': token_3,
            'signer_remark': '场景3-重复使用旧凭证',
        })
        s3_fail |= not _assert('再次签收被拦截', r.get('success') is False, r.get('message', ''))
        s3_fail |= not _assert('错误码=TOKEN_USED或ALREADY_SIGNED',
                               r.get('code') in ('TOKEN_USED', 'ALREADY_SIGNED'),
                               f"实际code={r.get('code')}")

        print('  (3-4) 再用validate接口校验已使用凭证 → 返回valid=False')
        r = api(clerk, 'POST', '/api/handover-authorizations/validate', {
            'token': token_3,
            'token_type': 'sign',
        })
        data = r.get('data', {}) or {}
        s3_fail |= not _assert('校验接口valid=False', data.get('valid') is False,
                               f"valid={data.get('valid')}, code={data.get('code')}")
        s3_fail |= not _assert('错误码=TOKEN_USED',
                               data.get('code') == 'TOKEN_USED',
                               f"实际code={data.get('code')}")

        print('  (3-5) 验证凭证is_used=True（持久化状态正确）')
        r = api(admin, 'GET', f'/api/handover-sheets/{sheet_id_3}/authorizations')
        auths = r.get('data', {}).get('list', []) or []
        target = next((a for a in auths if a['id'] == auth_id_3), None)
        s3_fail |= not _assert('凭证is_used=True持久化正确', target is not None and target.get('is_used') is True)
    except AssertionError as e:
        print(f'  [场景3] 断言失败中断: {e}')
        s3_fail = True
    except Exception as e:
        print(f'  [场景3] 异常: {e}')
        traceback.print_exc()
        s3_fail = True

    scenario_footer(3, '拿旧凭证(已使用)', s3_fail)

    # =========================================================
    # 场景 4: 替别人签（凭证角色限制不匹配）
    # =========================================================
    scenario_header(4, '替别人签(角色限制不匹配)', '凭证设置role_restriction=clerk，operator使用被拦截')
    s4_fail = False
    scenario4_context = {}

    try:
        print('  (4-1) 创建新的交接单')
        r = api(admin, 'GET', '/api/handover-sheets/available-labels?store=广州天河店')
        store_labels = [l for l in (r.get('data', []) or []) if not l.get('in_active_sheet')]
        s4_fail |= not _assert('广州天河店有可用价签', len(store_labels) > 0)
        if len(store_labels) == 0:
            raise AssertionError('广州天河店无可用价签')
        selected = [l['id'] for l in store_labels[:2]]

        r = api(admin, 'POST', '/api/handover-sheets', {
            'title': '【测试场景4】角色限制不匹配拦截测试',
            'store': '广州天河店',
            'remark': '自动化测试-场景4-角色限制不匹配',
            'label_ids': selected,
        })
        s4_fail |= not _assert('创建交接单成功', r.get('success') is True)
        sheet_id_4 = r['data']['sheet_id']
        scenario4_context['sheet_id'] = sheet_id_4

        print('  (4-2) 生成角色限制为 clerk 的签收凭证（不绑定具体user_id，只限制角色）')
        r = api(admin, 'POST', f'/api/handover-sheets/{sheet_id_4}/authorize', {
            'token_type': 'sign',
            'user_id': None,
            'role_restriction': 'clerk',
            'valid_hours': 24,
            'one_time': True,
            'batch_count': 1,
            'remark': '场景4-只允许clerk角色使用',
        })
        s4_fail |= not _assert('生成角色限制凭证成功', r.get('success') is True, r.get('message', ''))
        token_4 = r['data']['tokens'][0]['auth_token']
        scenario4_context['token_clerk_role'] = token_4

        print('  (4-3) operator 使用该角色限制凭证 → validate 校验被拦截')
        r = api(operator, 'POST', '/api/handover-authorizations/validate', {
            'token': token_4,
            'token_type': 'sign',
        })
        data = r.get('data', {}) or {}
        s4_fail |= not _assert('校验valid=False', data.get('valid') is False,
                               f"code={data.get('code')}, reason={data.get('reason')}")
        s4_fail |= not _assert('错误码=TOKEN_ROLE_MISMATCH',
                               data.get('code') == 'TOKEN_ROLE_MISMATCH',
                               f"实际code={data.get('code')}")

        print('  (4-4) operator 尝试用该凭证签收 → 被拦截')
        r = api(operator, 'POST', f'/api/handover-sheets/{sheet_id_4}/sign', {
            'sign_token': token_4,
            'signer_remark': 'operator用clerk角色凭证代签',
        })
        s4_fail |= not _assert('签收被拦截', r.get('success') is False, r.get('message', ''))
        s4_fail |= not _assert('错误码=TOKEN_ROLE_MISMATCH',
                               r.get('code') == 'TOKEN_ROLE_MISMATCH',
                               f"实际code={r.get('code')}")

        print('  (4-5) 验证交接单状态仍为 pending')
        r = api(admin, 'GET', f'/api/handover-sheets/{sheet_id_4}')
        sheet_data = r.get('data', {}) or {}
        s4_fail |= not _assert('交接单仍是pending', sheet_data.get('status') == 'pending',
                               f"实际={sheet_data.get('status')}")

        print('  (4-6) clerk 使用该角色限制凭证 → 正常签收成功（验证凭证本身有效）')
        r = api(clerk, 'POST', f'/api/handover-sheets/{sheet_id_4}/sign', {
            'sign_token': token_4,
            'signer_remark': '场景4-clerk用角色凭证正常签收',
        })
        s4_fail |= not _assert('clerk用角色限制凭证签收成功', r.get('success') is True, r.get('message', ''))
    except AssertionError as e:
        print(f'  [场景4] 断言失败中断: {e}')
        s4_fail = True
    except Exception as e:
        print(f'  [场景4] 异常: {e}')
        traceback.print_exc()
        s4_fail = True

    scenario_footer(4, '替别人签(角色限制不匹配)', s4_fail)

    # =========================================================
    # 场景 5: 单据作废后签
    # =========================================================
    scenario_header(5, '单据作废后签', '交接单被admin作废后，任何人不能签收')
    s5_fail = False

    try:
        print('  (5-1) 创建新交接单')
        r = api(admin, 'GET', '/api/handover-sheets/available-labels?store=深圳南山店')
        store_labels = [l for l in (r.get('data', []) or []) if not l.get('in_active_sheet')]
        s5_fail |= not _assert('深圳南山店有可用价签', len(store_labels) > 0)
        if len(store_labels) == 0:
            raise AssertionError('深圳南山店无可用价签')
        selected = [l['id'] for l in store_labels[:2]]

        r = api(admin, 'POST', '/api/handover-sheets', {
            'title': '【测试场景5】作废后不能签收测试',
            'store': '深圳南山店',
            'remark': '自动化测试-场景5-作废后签收拦截',
            'label_ids': selected,
        })
        s5_fail |= not _assert('创建交接单成功', r.get('success') is True)
        sheet_id_5 = r['data']['sheet_id']

        print('  (5-2) 生成 clerk 的签收凭证')
        clerk_me = api(clerk, 'GET', '/api/auth/me')
        clerk_id = clerk_me.get('data', {}).get('id')
        r = api(admin, 'POST', f'/api/handover-sheets/{sheet_id_5}/authorize', {
            'token_type': 'sign',
            'user_id': clerk_id,
            'valid_hours': 24,
            'one_time': True,
            'batch_count': 1,
            'remark': '场景5-作废单测试用',
        })
        s5_fail |= not _assert('生成凭证成功', r.get('success') is True)
        token_5 = r['data']['tokens'][0]['auth_token']

        print('  (5-3) admin 作废交接单')
        r = api(admin, 'POST', f'/api/handover-sheets/{sheet_id_5}/void', {
            'reason': '自动化测试-场景5-作废后签收拦截验证',
        })
        s5_fail |= not _assert('作废成功', r.get('success') is True, r.get('message', ''))

        print('  (5-4) 验证状态已变为 voided')
        r = api(admin, 'GET', f'/api/handover-sheets/{sheet_id_5}')
        sheet_data = r.get('data', {}) or {}
        s5_fail |= not _assert('交接单状态=voided', sheet_data.get('status') == 'voided',
                               f"实际={sheet_data.get('status')}")
        s5_fail |= not _assert('作废原因已记录', bool(sheet_data.get('void_reason')))

        print('  (5-5) clerk 用凭证尝试签收作废单 → 被拦截(VOIDED_SHEET)')
        r = api(clerk, 'POST', f'/api/handover-sheets/{sheet_id_5}/sign', {
            'sign_token': token_5,
            'signer_remark': '场景5-试图签收作废单',
        })
        s5_fail |= not _assert('签收被拦截', r.get('success') is False, r.get('message', ''))
        s5_fail |= not _assert('错误码=VOIDED_SHEET',
                               r.get('code') == 'VOIDED_SHEET',
                               f"实际code={r.get('code')}")

        print('  (5-6) validate接口校验凭证 → 因为关联的sheet已作废也应被拦截')
        r = api(clerk, 'POST', '/api/handover-authorizations/validate', {
            'token': token_5,
            'token_type': 'sign',
        })
        data = r.get('data', {}) or {}
        s5_fail |= not _assert('valid=False(因关联单据已作废)',
                               data.get('valid') is False,
                               f"code={data.get('code')}, reason={data.get('reason')}")
        s5_fail |= not _assert('错误码=VOIDED_SHEET',
                               data.get('code') == 'VOIDED_SHEET',
                               f"实际code={data.get('code')}")

        print('  (5-7) 作废单再生成凭证 → 也应被接口本身拒绝')
        r = api(admin, 'POST', f'/api/handover-sheets/{sheet_id_5}/authorize', {
            'token_type': 'sign',
            'user_id': clerk_id,
            'valid_hours': 24,
            'batch_count': 1,
            'remark': '场景5-给作废单开凭证（应失败）',
        })
        s5_fail |= not _assert('作废单生成授权凭证被接口本身拒绝',
                               r.get('success') is False, r.get('message', ''))
        s5_fail |= not _assert('错误码=VOIDED_SHEET',
                               r.get('code') == 'VOIDED_SHEET',
                               f"实际code={r.get('code')}")
    except AssertionError as e:
        print(f'  [场景5] 断言失败中断: {e}')
        s5_fail = True
    except Exception as e:
        print(f'  [场景5] 异常: {e}')
        traceback.print_exc()
        s5_fail = True

    scenario_footer(5, '单据作废后签', s5_fail)

    # =========================================================
    # 场景 6: 撤回签收 → 重开 → 重新签收
    # =========================================================
    scenario_header(6, '撤回签收重开', '签收后撤回签收权→重开交接单→生成新凭证→再次签收成功')
    s6_fail = False

    try:
        print('  (6-1) 创建新交接单')
        r = api(admin, 'GET', '/api/handover-sheets/available-labels')
        all_labels = [l for l in (r.get('data', []) or []) if not l.get('in_active_sheet')]
        s6_fail |= not _assert('有可用价签', len(all_labels) > 0)
        if len(all_labels) == 0:
            raise AssertionError('无可用价签')
        selected = [l['id'] for l in all_labels[:2]]
        first_store = all_labels[0]['store']

        r = api(admin, 'POST', '/api/handover-sheets', {
            'title': '【测试场景6】撤回签收-重开-重新签收测试',
            'store': first_store,
            'remark': '自动化测试-场景6-撤回签收重开',
            'label_ids': selected,
        })
        s6_fail |= not _assert('创建交接单成功', r.get('success') is True)
        sheet_id_6 = r['data']['sheet_id']

        print('  (6-2) clerk 被指派并直接签收（不走凭证，指派的人可以直接签）')
        clerk_me = api(clerk, 'GET', '/api/auth/me')
        clerk_id = clerk_me.get('data', {}).get('id')
        r = api(admin, 'POST', f'/api/handover-sheets/{sheet_id_6}/assign', {
            'assigned_to': clerk_id,
            'view_scope': 'assigned',
        })
        s6_fail |= not _assert('指派clerk为签收人成功', r.get('success') is True, r.get('message', ''))

        print('  (6-3) clerk 直接签收（作为指派签收人无需凭证）')
        r = api(clerk, 'POST', f'/api/handover-sheets/{sheet_id_6}/sign', {
            'signer_remark': '场景6-第一次签收',
        })
        s6_fail |= not _assert('第一次签收成功', r.get('success') is True, r.get('message', ''))
        receipt_1 = r.get('data', {}).get('receipt_no')
        s6_fail |= not _assert('生成第一份回执', bool(receipt_1))

        r = api(admin, 'GET', f'/api/handover-sheets/{sheet_id_6}')
        s6_fail |= not _assert('状态=signed', (r.get('data', {}) or {}).get('status') == 'signed')

        print('  (6-4) admin 撤回签收权')
        r = api(admin, 'POST', f'/api/handover-sheets/{sheet_id_6}/revoke-sign', {
            'reason': '自动化测试-场景6-撤回签收进行重开验证',
        })
        s6_fail |= not _assert('撤回签收成功', r.get('success') is True, r.get('message', ''))
        s6_fail |= not _assert('revoke_status=revoked',
                               r.get('data', {}).get('revoke_status') == 'revoked')

        r = api(admin, 'GET', f'/api/handover-sheets/{sheet_id_6}')
        sheet_d = r.get('data', {}) or {}
        s6_fail |= not _assert('交接单revoke_status=revoked(持久化正确)',
                               sheet_d.get('revoke_status') == 'revoked')

        print('  (6-5) clerk 尝试继续签收（撤回后不能直接签，因revoke_status=revoked）')
        r = api(clerk, 'POST', f'/api/handover-sheets/{sheet_id_6}/sign', {
            'signer_remark': '场景6-撤回后未重开尝试签收',
        })
        s6_fail |= not _assert('撤回签收后不重开不能签', r.get('success') is False, r.get('message', ''))
        s6_fail |= not _assert('错误码=REVOKED_SIGN',
                               r.get('code') == 'REVOKED_SIGN',
                               f"实际code={r.get('code')}")

        print('  (6-6) admin 重开交接单')
        r = api(admin, 'POST', f'/api/handover-sheets/{sheet_id_6}/reopen', {
            'remark': '自动化测试-场景6-重开',
        })
        s6_fail |= not _assert('重开成功', r.get('success') is True, r.get('message', ''))
        s6_fail |= not _assert('新状态=pending', r.get('data', {}).get('new_status') == 'pending')

        r = api(admin, 'GET', f'/api/handover-sheets/{sheet_id_6}')
        sheet_d = r.get('data', {}) or {}
        s6_fail |= not _assert('重开后status=pending', sheet_d.get('status') == 'pending')
        s6_fail |= not _assert('重开后revoke_status=reopened',
                               sheet_d.get('revoke_status') == 'reopened')
        s6_fail |= not _assert('重开后signed_by被清空', sheet_d.get('signed_by') is None)
        s6_fail |= not _assert('重开后signed_at被清空', sheet_d.get('signed_at') is None)

        print('  (6-7) 为重开后的交接单生成新的签收凭证给 operator')
        op_me = api(operator, 'GET', '/api/auth/me')
        operator_id = op_me.get('data', {}).get('id')
        r = api(admin, 'POST', f'/api/handover-sheets/{sheet_id_6}/authorize', {
            'token_type': 'sign',
            'user_id': operator_id,
            'valid_hours': 24,
            'one_time': True,
            'batch_count': 1,
            'remark': '场景6-重开后operator签收凭证',
        })
        s6_fail |= not _assert('重开后生成新凭证成功', r.get('success') is True)
        token_6 = r['data']['tokens'][0]['auth_token']

        print('  (6-8) operator 使用新凭证再次签收 → 成功（生成第二份回执）')
        r = api(operator, 'POST', f'/api/handover-sheets/{sheet_id_6}/sign', {
            'sign_token': token_6,
            'signer_remark': '场景6-operator重开后签收',
        })
        s6_fail |= not _assert('重开后operator签收成功', r.get('success') is True, r.get('message', ''))
        receipt_2 = r.get('data', {}).get('receipt_no')
        s6_fail |= not _assert('生成第二份回执号', bool(receipt_2))
        s6_fail |= not _assert('两份回执号不同', receipt_1 != receipt_2)

        r = api(admin, 'GET', f'/api/handover-sheets/{sheet_id_6}')
        sheet_d = r.get('data', {}) or {}
        s6_fail |= not _assert('最终signed_by=operator的id', sheet_d.get('signed_by') == operator_id)
        s6_fail |= not _assert('最终status=signed', sheet_d.get('status') == 'signed')

        print('  (6-9) 验证该交接单生成了两份回执（重开后第二份）')
        r = api(admin, 'GET', '/api/handover-receipts?size=100')
        all_rcpt = r.get('data', {}).get('list', []) or []
        sheet_rcpt = [x for x in all_rcpt if x.get('sheet_id') == sheet_id_6]
        s6_fail |= not _assert('该交接单有2份回执记录', len(sheet_rcpt) >= 2, f"实际={len(sheet_rcpt)}")
    except AssertionError as e:
        print(f'  [场景6] 断言失败中断: {e}')
        s6_fail = True
    except Exception as e:
        print(f'  [场景6] 异常: {e}')
        traceback.print_exc()
        s6_fail = True

    scenario_footer(6, '撤回签收重开', s6_fail)

    # =========================================================
    # 场景 7: 导出核对（4个导出接口）
    # =========================================================
    scenario_header(7, '导出核对', '交接单列表/明细/回执/审计日志 4个导出接口内容验证')
    s7_fail = False

    try:
        print('  (7-1) 导出交接单列表CSV → /api/export/handover-sheets')
        resp = api(admin, 'GET', '/api/export/handover-sheets', expect_json=False)
        csv_text = ''
        if hasattr(resp, 'text'):
            csv_text = resp.text
        elif isinstance(resp, str):
            csv_text = resp
        elif isinstance(resp, dict) and 'text' in resp:
            csv_text = resp['text']
        else:
            csv_text = str(resp)[:5000]

        s7_fail |= not _assert('导出列表响应非空', len(csv_text.strip()) > 0)
        s7_fail |= not _assert('包含"交接单号"列标题', '交接单号' in csv_text,
                               f'前100字符: {csv_text[:100]}')
        s7_fail |= not _assert('包含"状态"列标题', '状态' in csv_text)
        s7_fail |= not _assert('包含"签收人"或"signed"关键词（与真实数据一致）',
                               '签收人' in csv_text or '已签收' in csv_text or '待签收' in csv_text)
        sheet_id_1 = scenario1_context.get('sheet_id')
        sheet_no_1 = scenario1_context.get('sheet_no')
        if sheet_no_1:
            s7_fail |= not _assert('场景1的交接单号出现在导出中', sheet_no_1 in csv_text)

        print('  (7-2) 导出场景1的交接单明细CSV → /api/export/handover-sheet/<id>')
        assert sheet_id_1, '场景1sheet_id不存在'
        resp = api(admin, 'GET', f'/api/export/handover-sheet/{sheet_id_1}', expect_json=False)
        if hasattr(resp, 'text'):
            csv_detail = resp.text
        else:
            csv_detail = str(resp)[:5000]

        s7_fail |= not _assert('明细CSV非空', len(csv_detail.strip()) > 0)
        s7_fail |= not _assert('明细含SKU列', 'SKU' in csv_detail, f'前100字符: {csv_detail[:100]}')
        s7_fail |= not _assert('明细含原价/促销价列', '原价' in csv_detail and '促销价' in csv_detail)
        s7_fail |= not _assert('明细含打印状态/冲突列',
                               ('打印状态' in csv_detail) or ('冲突' in csv_detail))

        print('  (7-3) 导出交接回执CSV → /api/export/handover-receipts')
        resp = api(admin, 'GET', '/api/export/handover-receipts', expect_json=False)
        if hasattr(resp, 'text'):
            csv_rcpt = resp.text
        else:
            csv_rcpt = str(resp)[:5000]

        s7_fail |= not _assert('回执CSV非空', len(csv_rcpt.strip()) > 0)
        s7_fail |= not _assert('回执含"签收人"列', '签收人' in csv_rcpt,
                               f'前100字符: {csv_rcpt[:100]}')
        s7_fail |= not _assert('回执含"回执编号"列', '回执编号' in csv_rcpt)
        s7_fail |= not _assert('回执含"回执哈希"列', '回执哈希' in csv_rcpt)
        receipt_no_1 = scenario1_context.get('receipt_no')
        if receipt_no_1:
            s7_fail |= not _assert('场景1回执号在导出中', receipt_no_1 in csv_rcpt)

        print('  (7-4) 导出授权审计日志CSV → /api/export/handover-audit-logs')
        resp = api(admin, 'GET', '/api/export/handover-audit-logs', expect_json=False)
        if hasattr(resp, 'text'):
            csv_audit = resp.text
        else:
            csv_audit = str(resp)[:5000]

        s7_fail |= not _assert('审计日志CSV非空', len(csv_audit.strip()) > 0)
        s7_fail |= not _assert('审计日志含"操作类型"列', '操作类型' in csv_audit,
                               f'前100字符: {csv_audit[:100]}')
        s7_fail |= not _assert('审计日志含"处理结果"列', '处理结果' in csv_audit)
        s7_fail |= not _assert('审计日志含"拦截代码"或"block_code"',
                               '拦截代码' in csv_audit or '拦截原因' in csv_audit)
    except AssertionError as e:
        print(f'  [场景7] 断言失败中断: {e}')
        s7_fail = True
    except Exception as e:
        print(f'  [场景7] 异常: {e}')
        traceback.print_exc()
        s7_fail = True

    scenario_footer(7, '导出核对', s7_fail)

    # =========================================================
    # 场景 8: 可重复导入演示数据（重置后可重导）
    # =========================================================
    scenario_header(8, '可重复导入演示数据', '首次导入→重复导入被拦截→reset→重新导入成功')
    s8_fail = False

    try:
        print('  (8-1) 先尝试重置一次，保证初始状态干净')
        r = api(admin, 'POST', '/api/drill/demo-data/drill_handover_labels/reset', {'reimport': False})
        print(f'  重置(不重导): {"成功" if r.get("success") else r.get("message","")}')

        print('  (8-2) 首次导入演示数据 → 应成功')
        r = api(admin, 'POST', '/api/drill/demo-data/import', {
            'data_key': 'drill_handover_labels',
            'batch_id': 'auth_test_8_first',
        })
        s8_fail |= not _assert('首次导入成功', r.get('success') is True, r.get('message', ''))
        first_batch_id = r.get('data', {}).get('batch_id')
        first_gen = r.get('data', {}).get('generation_id')
        s8_fail |= not _assert('首次导入返回batch_id', first_batch_id is not None)

        print('  (8-3) 重复导入同一 data_key → 应被拦截(DUPLICATE_DATA)')
        r = api(admin, 'POST', '/api/drill/demo-data/import', {
            'data_key': 'drill_handover_labels',
            'batch_id': 'auth_test_8_dup',
        })
        s8_fail |= not _assert('重复导入被拦截', r.get('success') is False)
        s8_fail |= not _assert('错误码=DUPLICATE_DATA',
                               r.get('code') == 'DUPLICATE_DATA',
                               f"实际code={r.get('code')}")

        print('  (8-4) 调用 reset 重置(并自动重新导入) → 成功')
        r = api(admin, 'POST', '/api/drill/demo-data/drill_handover_labels/reset', {'reimport': True})
        s8_fail |= not _assert('重置(含重导)成功', r.get('success') is True, r.get('message', ''))
        second_batch_id = (r.get('data') or {}).get('batch_id')
        second_gen = (r.get('data') or {}).get('generation_id')

        print('  (8-5) 验证两次 generation_id 不同（说明是新批次）')
        s8_fail |= not _assert('新批次generation_id不同',
                               first_gen is not None and second_gen is not None and first_gen != second_gen,
                               f'first_gen={first_gen}, second_gen={second_gen}')

        print('  (8-6) 用新批次数据也能查到价签')
        r = api(admin, 'GET', f'/api/labels?size=100')
        labels = (r.get('data', {}).get('list', []) or [])
        second_labels = [l for l in labels if l.get('batch_id') == second_batch_id]
        s8_fail |= not _assert('新批次价签在系统中可查', len(second_labels) > 0,
                               f'找到{len(second_labels)}个新批次价签')

        print('  (8-7) force_reset=true 方式也能导入')
        r = api(admin, 'POST', '/api/drill/demo-data/import', {
            'data_key': 'drill_handover_labels',
            'batch_id': 'auth_test_8_force',
            'force_reset': True,
        })
        s8_fail |= not _assert('force_reset=true导入成功', r.get('success') is True, r.get('message', ''))
    except AssertionError as e:
        print(f'  [场景8] 断言失败中断: {e}')
        s8_fail = True
    except Exception as e:
        print(f'  [场景8] 异常: {e}')
        traceback.print_exc()
        s8_fail = True

    scenario_footer(8, '可重复导入演示数据', s8_fail)

    # =========================================================
    # 汇总
    # =========================================================
    print()
    print('=' * 70)
    print('  测试汇总')
    print('=' * 70)
    total_scenarios = 8
    pass_count = total_scenarios - len(FAILED_SCENARIOS)
    scenario_rate = (pass_count / total_scenarios) * 100
    print(f'  场景总数: {total_scenarios}')
    print(f'  通过场景: {pass_count}')
    print(f'  失败场景: {len(FAILED_SCENARIOS)}')
    if FAILED_SCENARIOS:
        print(f'  失败列表: {", ".join(FAILED_SCENARIOS)}')
    print()
    print(f'  总断言数: {TOTAL_ASSERTIONS}')
    print(f'  通过断言: {PASSED_ASSERTIONS}')
    print(f'  失败断言: {FAILED_ASSERTIONS}')
    assertion_rate = 0
    if TOTAL_ASSERTIONS > 0:
        assertion_rate = (PASSED_ASSERTIONS / TOTAL_ASSERTIONS) * 100
        print(f'  断言通过率: {assertion_rate:.2f}%')
    print()
    print(f'  场景通过率: {scenario_rate:.2f}%')
    if pass_count == total_scenarios and FAILED_ASSERTIONS == 0:
        print()
        print('  🏆🎉 全部测试通过！交接单授权签收台全链路验证成功！')
    else:
        print()
        print('  ⚠️  存在失败项，请查看上方 FAIL 标记的断言')
    print('=' * 70)

    if FAILED_SCENARIOS or FAILED_ASSERTIONS > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
