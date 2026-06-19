import urllib.request, urllib.parse, json, http.cookiejar

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

def call(method, path, data=None, is_json=True, multipart=None):
    url = f'http://localhost:5000{path}'
    if multipart:
        boundary = '----TestBoundary123456'
        body = b''
        for key, (fname, fdata, ctype) in multipart.items():
            body += f'------TestBoundary123456\r\nContent-Disposition: form-data; name="{key}"; filename="{fname}"\r\nContent-Type: {ctype}\r\n\r\n'.encode() + fdata + b'\r\n'
        body += b'------TestBoundary123456--\r\n'
        req = urllib.request.Request(url, data=body, method='POST')
        req.add_header('Content-Type', f'multipart/form-data; boundary=----TestBoundary123456')
    elif is_json and data:
        req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), method=method)
        req.add_header('Content-Type', 'application/json')
    else:
        req = urllib.request.Request(url, method=method)
    resp = json.loads(opener.open(req).read())
    return resp

# 1. 登录 admin
r = call('POST', '/api/auth/login', {'username': 'admin', 'password': 'admin123'})
print('1. 登录 admin:', '✅' if r.get('success') else '❌', r.get('message'))

# 2. 测试 clerk 无审批权限（越权校验）
cj2 = http.cookiejar.CookieJar()
opener2 = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj2))
def call2(method, path, data=None):
    url = f'http://localhost:5000{path}'
    req = urllib.request.Request(url, data=json.dumps(data or {}).encode(), method=method)
    req.add_header('Content-Type', 'application/json')
    try:
        return json.loads(opener2.open(req).read())
    except urllib.error.HTTPError as e:
        return {'success': False, 'status': e.code, 'message': json.loads(e.read()).get('message', str(e))}

r = call2('POST', '/api/auth/login', {'username': 'clerk', 'password': 'clerk123'})
print('2. 登录 clerk:', '✅' if r.get('success') else '❌')
r = call2('POST', '/api/labels/approve', {'label_ids': [1], 'approve': True})
print('3. 店员越权审批拦截:', '✅ 已拦截' if r.get('status') == 403 else '❌ 未拦截', r.get('message'))

# 4. 导入CSV测试 - 包含异常数据
csv_content = '''SKU,门店,原价,促销价,生效开始时间,生效结束时间,模板
SKU001,北京朝阳店,99.00,69.00,2026-07-01 00:00:00,2026-07-31 23:59:59,default
SKU002,上海浦东店,199.00,149.00,2026-07-01 00:00:00,2026-07-15 23:59:59,promotion
SKU003,广州天河店,100.00,150.00,2026-07-01 00:00:00,2026-07-31 23:59:59,default
SKU004,不存在的店,100.00,50.00,2026-07-01 00:00:00,2026-07-31 23:59:59,default
SKU005,深圳南山店,100.00,40.00,2026-07-01 00:00:00,2026-07-31 23:59:59,default
SKU001,北京朝阳店,99.00,79.00,2026-07-15 00:00:00,2026-08-15 23:59:59,default
'''
files = {'file': ('test.csv', csv_content.encode('utf-8-sig'), 'text/csv')}
r = call('POST', '/api/import', multipart=files)
print('4. CSV导入:', '✅' if r.get('success') else '❌')
print('   - 校验通过:', r['data']['valid_rows'], '/', r['data']['total_rows'])
print('   - 校验失败:', r['data']['invalid_rows'])
for v in r['data']['validation_results'][:6]:
    status = '✅通过' if v['is_valid'] else f"❌{';'.join(v['errors'][:1])}"
    print(f'   行{v["row_number"]} {v["parsed"]["sku"]} {v["parsed"]["store"]} -> {status}')

# 5. 获取批次ID和价签ID
batch_id = r['data']['batch_id']
r = call('GET', f'/api/labels?batch_id={batch_id}')
print('5. 草稿价签数:', len(r['data']['list']))
label_ids = [l['id'] for l in r['data']['list']]

# 6. 提交审批
r = call('POST', '/api/labels/submit', {'label_ids': label_ids})
print('6. 提交审批:', '✅' if r.get('success') else '❌', f"成功{r['data']['success_count']}条")

# 7. 审批通过（管理员）
r = call('POST', '/api/labels/approve', {'label_ids': label_ids, 'approve': True})
print('7. 审批通过:', '✅' if r.get('success') else '❌', f"成功{r['data']['success_count']}条")

# 8. 查看打印清单
r = call('GET', '/api/print-queue')
print('8. 待打印清单:', len(r['data']['list']), '条')

# 9. 测试重叠时段导入拦截
csv2 = 'SKU,门店,原价,促销价,生效开始时间,生效结束时间,模板\nSKU001,北京朝阳店,99,70,2026-07-10 00:00:00,2026-07-20 23:59:59,default\n'
files2 = {'file': ('test2.csv', csv2.encode('utf-8-sig'), 'text/csv')}
r = call('POST', '/api/import', multipart=files2)
print('9. 重复生效窗口拦截:', '✅ 已拦截' if r['data']['invalid_rows'] == 1 else '❌ 未拦截', r['data']['validation_results'][0]['errors'])

# 10. 回滚价签
r = call('GET', f'/api/labels?status=published')
published_ids = [l['id'] for l in r['data']['list'][:1]]
if published_ids:
    r = call('POST', f'/api/labels/{published_ids[0]}/rollback', {'reason': '测试回滚'})
    print('10. 回滚价签:', '✅' if r.get('success') else '❌', r.get('message'))
    r = call('GET', '/api/rollback-history')
    print('11. 回滚历史记录:', len(r['data']['list']), '条')

# 12. 测试不存在的版本回滚
r = call('GET', f'/api/labels?status=published')
if r['data']['list']:
    lid = r['data']['list'][0]['id']
    r = call('POST', f'/api/labels/{lid}/rollback', {'reason': '测试不存在版本', 'target_version': 9999})
    print('12. 不存在版本回滚拦截:', '✅' if not r.get('success') else '❌', r.get('message'))

# 13. 导出测试
import urllib.request as u2
req = u2.Request('http://localhost:5000/api/export/labels')
cookies_str = '; '.join([f'{c.name}={c.value}' for c in cj])
req.add_header('Cookie', cookies_str)
resp = u2.urlopen(req)
content = resp.read().decode('utf-8-sig')
print('13. 导出CSV:', '✅' if 'SKU' in content else '❌', f'大小={len(content)}字节')

print('\n========== 所有测试完成 ==========')
