import os
import json
import uuid
from datetime import datetime, timedelta
from io import StringIO

from flask import Flask, request, jsonify, send_file, g, session, make_response
from flask_cors import CORS
import pandas as pd
from dateutil import parser as date_parser

from models import (
    db, User, SystemConfig, ImportBatch, ImportValidation,
    PriceLabel, RollbackHistory, PrintQueue, RevocationLog,
    RevocationRequest, RevocationRequestLog,
    HandoverSheet, HandoverItem, HandoverLog
)
from validation import check_publish_approval, is_in_publish_window

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, 'instance')
os.makedirs(INSTANCE_DIR, exist_ok=True)

app = Flask(__name__, instance_path=INSTANCE_DIR)
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(INSTANCE_DIR, "pricelabel.db")}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'pricelabel-workbench-secret-key-2024'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB

CORS(app, supports_credentials=True, resources={r"/*": {"origins": "*"}})
db.init_app(app)


# ==================== 初始化数据 ====================
def init_default_data():
    with app.app_context():
        db.create_all()

        if not User.query.first():
            admin = User(username='admin', role='admin')
            admin.set_password('admin123')
            operator = User(username='operator', role='operator')
            operator.set_password('operator123')
            clerk = User(username='clerk', role='clerk')
            clerk.set_password('clerk123')
            db.session.add_all([admin, operator, clerk])

        default_configs = {
            'discount_floor': '0.5',
            'store_whitelist': json.dumps(['北京朝阳店', '上海浦东店', '广州天河店', '深圳南山店']),
            'template_fields': json.dumps([
                {'key': 'sku', 'label': 'SKU编码', 'required': True},
                {'key': 'product_name', 'label': '商品名称', 'required': False},
                {'key': 'original_price', 'label': '原价', 'required': True},
                {'key': 'promotion_price', 'label': '促销价', 'required': True},
                {'key': 'effective_from', 'label': '生效开始时间', 'required': True},
                {'key': 'effective_to', 'label': '生效结束时间', 'required': True}
            ]),
            'publish_window': json.dumps({
                'enabled': True,
                'start_hour': 9,
                'end_hour': 18,
                'weekdays_only': True
            })
        }
        for key, value in default_configs.items():
            if not SystemConfig.query.filter_by(config_key=key).first():
                db.session.add(SystemConfig(config_key=key, config_value=value, updated_by=1))

        db.session.commit()


# ==================== 工具函数 ====================
def get_config(key, default=None):
    cfg = SystemConfig.query.filter_by(config_key=key).first()
    if cfg:
        try:
            return json.loads(cfg.config_value)
        except (json.JSONDecodeError, TypeError):
            return cfg.config_value
    return default


def save_config(key, value, user_id=1):
    cfg = SystemConfig.query.filter_by(config_key=key).first()
    str_val = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    if cfg:
        cfg.config_value = str_val
        cfg.updated_by = user_id
        cfg.updated_at = datetime.utcnow()
    else:
        db.session.add(SystemConfig(config_key=key, config_value=str_val, updated_by=user_id))


def get_current_user():
    user_id = session.get('user_id')
    if user_id:
        return User.query.get(user_id)
    return None


def require_login(f):
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'success': False, 'message': '请先登录', 'code': 401}), 401
        g.current_user = user
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper


def require_roles(*roles):
    def decorator(f):
        def wrapper(*args, **kwargs):
            user = get_current_user()
            if not user:
                return jsonify({'success': False, 'message': '请先登录', 'code': 401}), 401
            if user.role not in roles:
                return jsonify({'success': False, 'message': '权限不足', 'code': 403}), 403
            g.current_user = user
            return f(*args, **kwargs)
        wrapper.__name__ = f.__name__
        return wrapper
    return decorator


def parse_datetime(s):
    if not s or (isinstance(s, float) and pd.isna(s)):
        return None
    try:
        if isinstance(s, datetime):
            return s
        return date_parser.parse(str(s))
    except Exception:
        return None


def validate_label_row(row, discount_floor, store_whitelist, check_overlap=True):
    errors = []

    sku = str(row.get('SKU', '')).strip()
    if not sku:
        errors.append('SKU不能为空')

    store = str(row.get('门店', '')).strip()
    if not store:
        errors.append('门店不能为空')
    elif store_whitelist and store not in store_whitelist:
        errors.append(f'门店"{store}"不在白名单中')

    try:
        original_price = float(row.get('原价', 0) or 0)
    except (ValueError, TypeError):
        original_price = 0
        errors.append('原价格式错误')

    try:
        promotion_price = float(row.get('促销价', 0) or 0)
    except (ValueError, TypeError):
        promotion_price = 0
        errors.append('促销价格式错误')

    if original_price <= 0:
        errors.append('原价必须大于0')
    if promotion_price < 0:
        errors.append('促销价不能为负数')

    if original_price > 0 and promotion_price > original_price:
        errors.append('促销价不能高于原价')

    if original_price > 0 and promotion_price > 0:
        discount = promotion_price / original_price
        if discount < float(discount_floor):
            errors.append(f'折扣低于下限{float(discount_floor)*100:.0f}%')

    effective_from = parse_datetime(row.get('生效时间', ''))
    if isinstance(row, dict) and '生效开始时间' in row:
        effective_from = parse_datetime(row.get('生效开始时间', ''))
    effective_to = parse_datetime(row.get('生效结束时间', ''))

    if not effective_from:
        errors.append('生效开始时间格式错误')
    if not effective_to:
        errors.append('生效结束时间格式错误')
    if effective_from and effective_to and effective_from >= effective_to:
        errors.append('生效开始时间必须早于结束时间')

    template = str(row.get('模板', 'default')).strip() or 'default'

    if check_overlap and sku and store and effective_from and effective_to:
        overlap = PriceLabel.query.filter(
            PriceLabel.sku == sku,
            PriceLabel.store == store,
            PriceLabel.status.in_(['pending_approval', 'published', 'revoking']),
            PriceLabel.effective_from < effective_to,
            PriceLabel.effective_to > effective_from
        ).first()
        if overlap:
            status_label = {
                'pending_approval': '待审批',
                'published': '已发布',
                'revoking': '撤销中'
            }.get(overlap.status, overlap.status)
            errors.append(f'与已有价签(ID:{overlap.id}, {status_label})生效时段重叠')

    return {
        'is_valid': len(errors) == 0,
        'errors': errors,
        'parsed': {
            'sku': sku,
            'store': store,
            'original_price': original_price,
            'promotion_price': promotion_price,
            'effective_from': effective_from,
            'effective_to': effective_to,
            'template': template
        }
    }



# ==================== 认证接口 ====================
@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        return jsonify({'success': False, 'message': '用户名或密码错误'})
    session['user_id'] = user.id
    return jsonify({'success': True, 'data': user.to_dict()})


@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})


@app.route('/api/auth/me', methods=['GET'])
def me():
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'message': '未登录', 'code': 401}), 401
    return jsonify({'success': True, 'data': user.to_dict()})


# ==================== 系统配置接口 ====================
@app.route('/api/config', methods=['GET'])
@require_login
def get_all_config():
    configs = SystemConfig.query.all()
    result = {}
    for cfg in configs:
        try:
            result[cfg.config_key] = json.loads(cfg.config_value)
        except (json.JSONDecodeError, TypeError):
            result[cfg.config_key] = cfg.config_value
    return jsonify({'success': True, 'data': result})


@app.route('/api/config', methods=['PUT'])
@require_roles('admin')
def update_config():
    data = request.get_json() or {}
    user = g.current_user
    for key, value in data.items():
        save_config(key, value, user.id)
    db.session.commit()
    return jsonify({'success': True, 'message': '配置已更新'})


# ==================== 导入接口 ====================
@app.route('/api/import', methods=['POST'])
@require_roles('admin', 'operator')
def import_csv():
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': '未找到上传文件'})
    file = request.files['file']
    if not file.filename:
        return jsonify({'success': False, 'message': '文件名为空'})

    try:
        content = file.read().decode('utf-8-sig')
        df = pd.read_csv(StringIO(content))
    except UnicodeDecodeError:
        file.seek(0)
        try:
            content = file.read().decode('gbk')
            df = pd.read_csv(StringIO(content))
        except Exception as e:
            return jsonify({'success': False, 'message': f'文件编码错误: {str(e)}'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'文件解析失败: {str(e)}'})

    required_cols = ['SKU', '门店', '原价', '促销价', '生效时间', '模板']
    alt_cols = {'生效开始时间': '生效时间', '生效结束时间': None}

    columns = list(df.columns)
    missing = [c for c in required_cols if c not in columns and c != '生效时间']
    if '生效时间' not in columns and '生效开始时间' not in columns:
        missing.append('生效时间/生效开始时间')
    if missing:
        return jsonify({'success': False, 'message': f'缺少必要列: {", ".join(missing)}'})

    user = g.current_user
    batch_no = f'BATCH{datetime.now().strftime("%Y%m%d%H%M%S")}{uuid.uuid4().hex[:6].upper()}'
    batch = ImportBatch(
        batch_no=batch_no,
        filename=file.filename,
        total_rows=len(df),
        imported_by=user.id
    )
    db.session.add(batch)
    db.session.flush()

    discount_floor = get_config('discount_floor', '0.5')
    store_whitelist = get_config('store_whitelist', [])

    valid_count = 0
    invalid_count = 0
    validation_results = []

    for idx, row in df.iterrows():
        row_dict = row.to_dict()
        if '生效开始时间' in row_dict and '生效时间' not in row_dict:
            row_dict['生效时间'] = row_dict['生效开始时间']

        result = validate_label_row(row_dict, discount_floor, store_whitelist)
        parsed = result['parsed']

        validation = ImportValidation(
            batch_id=batch.id,
            row_number=idx + 2,
            sku=parsed['sku'],
            store=parsed['store'],
            original_price=parsed['original_price'],
            promotion_price=parsed['promotion_price'],
            effective_from=parsed['effective_from'].isoformat() if parsed['effective_from'] else '',
            effective_to=parsed['effective_to'].isoformat() if parsed['effective_to'] else '',
            template=parsed['template'],
            is_valid=result['is_valid'],
            error_message='; '.join(result['errors']) if result['errors'] else ''
        )
        db.session.add(validation)
        validation_results.append({
            'row_number': idx + 2,
            'is_valid': result['is_valid'],
            'errors': result['errors'],
            'parsed': {
                k: v.isoformat() if isinstance(v, datetime) else v
                for k, v in parsed.items()
            }
        })

        if result['is_valid']:
            valid_count += 1
            label = PriceLabel(
                sku=parsed['sku'],
                store=parsed['store'],
                original_price=parsed['original_price'],
                promotion_price=parsed['promotion_price'],
                effective_from=parsed['effective_from'],
                effective_to=parsed['effective_to'],
                template=parsed['template'],
                status='draft',
                version=1,
                batch_id=batch.id,
                created_by=user.id
            )
            db.session.add(label)
        else:
            invalid_count += 1

    batch.valid_rows = valid_count
    batch.invalid_rows = invalid_count
    batch.status = 'completed'
    db.session.commit()

    return jsonify({
        'success': True,
        'data': {
            'batch_id': batch.id,
            'batch_no': batch_no,
            'total_rows': batch.total_rows,
            'valid_rows': valid_count,
            'invalid_rows': invalid_count,
            'validation_results': validation_results[:100],
            'has_more': len(validation_results) > 100
        }
    })


@app.route('/api/import/batches', methods=['GET'])
@require_login
def list_batches():
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 20, type=int)
    query = ImportBatch.query.order_by(ImportBatch.created_at.desc())
    total = query.count()
    batches = query.offset((page - 1) * size).limit(size).all()
    data = []
    for b in batches:
        data.append({
            'id': b.id,
            'batch_no': b.batch_no,
            'filename': b.filename,
            'total_rows': b.total_rows,
            'valid_rows': b.valid_rows,
            'invalid_rows': b.invalid_rows,
            'status': b.status,
            'created_at': b.created_at.isoformat(),
            'imported_by': b.imported_by
        })
    return jsonify({'success': True, 'data': {'list': data, 'total': total}})


@app.route('/api/import/batches/<int:batch_id>', methods=['GET'])
@require_login
def get_batch_detail(batch_id):
    batch = ImportBatch.query.get(batch_id)
    if not batch:
        return jsonify({'success': False, 'message': '批次不存在'}), 404

    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 50, type=int)
    only_invalid = request.args.get('only_invalid', 'false').lower() == 'true'

    query = ImportValidation.query.filter_by(batch_id=batch_id)
    if only_invalid:
        query = query.filter_by(is_valid=False)

    total = query.count()
    validations = query.order_by(ImportValidation.row_number).offset((page - 1) * size).limit(size).all()

    data = []
    for v in validations:
        data.append({
            'id': v.id,
            'row_number': v.row_number,
            'sku': v.sku,
            'store': v.store,
            'original_price': v.original_price,
            'promotion_price': v.promotion_price,
            'effective_from': v.effective_from,
            'effective_to': v.effective_to,
            'template': v.template,
            'is_valid': v.is_valid,
            'error_message': v.error_message
        })

    return jsonify({
        'success': True,
        'data': {
            'batch': {
                'id': batch.id,
                'batch_no': batch.batch_no,
                'filename': batch.filename,
                'total_rows': batch.total_rows,
                'valid_rows': batch.valid_rows,
                'invalid_rows': batch.invalid_rows,
                'status': batch.status,
                'created_at': batch.created_at.isoformat()
            },
            'validations': {'list': data, 'total': total}
        }
    })


# ==================== 价签接口 ====================
@app.route('/api/labels', methods=['GET'])
@require_login
def list_labels():
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 20, type=int)
    status = request.args.get('status', '')
    sku = request.args.get('sku', '')
    store = request.args.get('store', '')

    query = PriceLabel.query
    if status:
        query = query.filter_by(status=status)
    if sku:
        query = query.filter(PriceLabel.sku.like(f'%{sku}%'))
    if store:
        query = query.filter(PriceLabel.store.like(f'%{store}%'))

    total = query.count()
    labels = query.order_by(PriceLabel.created_at.desc()).offset((page - 1) * size).limit(size).all()

    return jsonify({
        'success': True,
        'data': {
            'list': [l.to_dict(include_detail=True) for l in labels],
            'total': total
        }
    })


@app.route('/api/labels/<int:label_id>', methods=['GET'])
@require_login
def get_label_detail(label_id):
    label = PriceLabel.query.get(label_id)
    if not label:
        return jsonify({'success': False, 'message': '价签不存在'}), 404

    history = RollbackHistory.query.filter_by(label_id=label_id).order_by(RollbackHistory.created_at.desc()).all()
    versions = PriceLabel.query.filter_by(sku=label.sku, store=label.store).order_by(PriceLabel.version).all()
    revocation_logs = RevocationLog.query.filter_by(label_id=label_id).order_by(RevocationLog.created_at.desc()).all()
    revocation_requests = RevocationRequest.query.filter_by(label_id=label_id).order_by(RevocationRequest.requested_at.desc()).all()

    req_list = []
    for req in revocation_requests:
        d = req.to_dict()
        d['requested_by_name'] = _get_username(req.requested_by)
        d['reviewed_by_name'] = _get_username(req.reviewed_by)
        req_list.append(d)

    return jsonify({
        'success': True,
        'data': {
            'label': label.to_dict(include_detail=True),
            'rollback_history': [h.to_dict() for h in history],
            'revocation_logs': [r.to_dict() for r in revocation_logs],
            'revocation_requests': req_list,
            'versions': [{
                'id': v.id,
                'version': v.version,
                'status': v.status,
                'promotion_price': v.promotion_price,
                'effective_from': v.effective_from.isoformat(),
                'effective_to': v.effective_to.isoformat(),
                'created_at': v.created_at.isoformat()
            } for v in versions]
        }
    })


@app.route('/api/labels/submit', methods=['POST'])
@require_roles('admin', 'operator')
def submit_labels():
    data = request.get_json() or {}
    label_ids = data.get('label_ids', [])
    if not label_ids:
        return jsonify({'success': False, 'message': '未选择价签'})

    user = g.current_user
    now = datetime.utcnow()
    success_count = 0
    failed = []

    for lid in label_ids:
        label = PriceLabel.query.get(lid)
        if not label:
            failed.append({'id': lid, 'reason': '价签不存在'})
            continue
        if label.status != 'draft':
            failed.append({'id': lid, 'reason': f'状态为{label.status}，不能提交'})
            continue

        label.status = 'pending_approval'
        label.submitted_at = now
        success_count += 1

    db.session.commit()
    return jsonify({
        'success': True,
        'data': {
            'success_count': success_count,
            'failed': failed
        }
    })


@app.route('/api/labels/approve', methods=['POST'])
@require_roles('admin')
def approve_labels():
    data = request.get_json() or {}
    label_ids = data.get('label_ids', [])
    approve = data.get('approve', True)
    reject_reason = data.get('reject_reason', '')

    if not label_ids:
        return jsonify({'success': False, 'message': '未选择价签'})

    user = g.current_user
    now = datetime.utcnow()
    success_count = 0
    failed = []

    if approve:
        check_results = check_publish_approval(label_ids)

        for lid in label_ids:
            r = check_results.get(lid)
            if not r:
                failed.append({'id': lid, 'reason': '价签不存在'})
                continue
            if r['group'] != 'publishable':
                failed.append({'id': lid, 'reason': r['risk_reason']})
                continue

            label = PriceLabel.query.get(lid)
            label.status = 'published'
            label.approved_at = now
            label.approved_by = user.id
            label.published_at = now
            label.published_by = user.id

            pq = PrintQueue(
                label_id=label.id,
                store=label.store,
                sku=label.sku,
                original_price=label.original_price,
                promotion_price=label.promotion_price,
                effective_from=label.effective_from,
                effective_to=label.effective_to,
                template=label.template
            )
            db.session.add(pq)
            success_count += 1
    else:
        for lid in label_ids:
            label = PriceLabel.query.get(lid)
            if not label:
                failed.append({'id': lid, 'reason': '价签不存在'})
                continue
            if label.status != 'pending_approval':
                failed.append({'id': lid, 'reason': f'状态为{label.status}，不能审批'})
                continue
            label.status = 'draft'
            if reject_reason:
                label.rollback_reason = f'驳回原因: {reject_reason}'
            success_count += 1

    db.session.commit()
    return jsonify({
        'success': True,
        'data': {
            'success_count': success_count,
            'failed': failed
        }
    })


@app.route('/api/labels/precheck', methods=['POST'])
@require_roles('admin')
def precheck_labels():
    data = request.get_json() or {}
    label_ids = data.get('label_ids', [])
    if not label_ids:
        return jsonify({'success': False, 'message': '未选择价签'})

    check_results = check_publish_approval(label_ids)

    publishable = []
    conflict = []
    config_restricted = []

    for lid in label_ids:
        r = check_results.get(lid)
        if not r:
            item = {
                'label_id': lid, 'sku': '', 'store': '',
                'effective_from': '', 'effective_to': '',
                'risk_reason': '价签不存在', 'suggested_action': '检查价签ID是否正确',
            }
            config_restricted.append(item)
            continue
        item = {
            'label_id': r['label_id'],
            'sku': r['sku'],
            'store': r['store'],
            'effective_from': r['effective_from'],
            'effective_to': r['effective_to'],
            'risk_reason': r['risk_reason'],
            'suggested_action': r['suggested_action'],
        }
        group = r['group']
        if group == 'publishable':
            publishable.append(item)
        elif group == 'conflict':
            conflict.append(item)
        else:
            config_restricted.append(item)

    return jsonify({
        'success': True,
        'data': {
            'publishable': publishable,
            'conflict': conflict,
            'config_restricted': config_restricted,
            'total': len(label_ids),
            'publishable_count': len(publishable),
            'conflict_count': len(conflict),
            'config_restricted_count': len(config_restricted),
        }
    })


@app.route('/api/export/precheck', methods=['POST'])
@require_roles('admin')
def export_precheck():
    data = request.get_json() or {}
    label_ids = data.get('label_ids', [])
    if not label_ids:
        return jsonify({'success': False, 'message': '未选择价签'})

    check_results = check_publish_approval(label_ids)

    group_map = {
        'publishable': '可发布',
        'conflict': '冲突',
        'config_restricted': '配置限制',
    }

    rows = []
    for lid in label_ids:
        r = check_results.get(lid)
        if not r:
            rows.append({
                '价签ID': lid, 'SKU': '', '门店': '',
                '生效开始时间': '', '生效结束时间': '',
                '分组': '配置限制',
                '风险原因': '价签不存在',
                '建议动作': '检查价签ID是否正确',
            })
            continue
        rows.append({
            '价签ID': r['label_id'],
            'SKU': r['sku'],
            '门店': r['store'],
            '生效开始时间': r['effective_from'],
            '生效结束时间': r['effective_to'],
            '分组': group_map.get(r['group'], r['group']),
            '风险原因': r['risk_reason'] or '无',
            '建议动作': r['suggested_action'],
        })

    columns = ['价签ID', 'SKU', '门店', '生效开始时间', '生效结束时间', '分组', '风险原因', '建议动作']
    df = pd.DataFrame(rows, columns=columns)
    output = StringIO()
    df.to_csv(output, index=False, encoding='utf-8-sig', lineterminator='\n')
    output.seek(0)

    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = f'attachment; filename=precheck_{datetime.now().strftime("%Y%m%d%H%M%S")}.csv'
    return resp


@app.route('/api/labels/<int:label_id>/rollback', methods=['POST'])
@require_roles('admin')
def rollback_label(label_id):
    data = request.get_json() or {}
    reason = data.get('reason', '')
    target_version = data.get('target_version')

    label = PriceLabel.query.get(label_id)
    if not label:
        return jsonify({'success': False, 'message': '价签不存在'}), 404

    if label.status != 'published':
        return jsonify({'success': False, 'message': '只有已发布状态才能回滚'})

    user = g.current_user
    now = datetime.utcnow()

    if target_version is not None:
        target = PriceLabel.query.filter_by(
            sku=label.sku, store=label.store, version=int(target_version)
        ).first()
        if not target:
            return jsonify({'success': False, 'message': f'版本v{target_version}不存在'})
        if target.id == label.id:
            return jsonify({'success': False, 'message': '不能回滚到当前版本'})

        new_version = PriceLabel(
            sku=target.sku,
            store=target.store,
            original_price=target.original_price,
            promotion_price=target.promotion_price,
            effective_from=target.effective_from,
            effective_to=target.effective_to,
            template=target.template,
            status='published',
            version=label.version + 1,
            batch_id=label.batch_id,
            created_by=user.id,
            approved_at=now,
            approved_by=user.id,
            published_at=now,
            published_by=user.id,
            previous_version_id=label.id
        )

        overlap = PriceLabel.query.filter(
            PriceLabel.sku == new_version.sku,
            PriceLabel.store == new_version.store,
            PriceLabel.id != label.id,
            PriceLabel.status.in_(['pending_approval', 'published']),
            PriceLabel.effective_from < new_version.effective_to,
            PriceLabel.effective_to > new_version.effective_from
        ).first()
        if overlap:
            return jsonify({'success': False, 'message': f'回滚后与价签(ID:{overlap.id})生效时段重叠'})

        db.session.add(new_version)
        db.session.flush()

        label.status = 'rolled_back'
        label.rolled_back_at = now
        label.rolled_back_by = user.id
        label.rollback_reason = reason

        rh = RollbackHistory(
            label_id=label.id,
            from_version=label.version,
            to_version=new_version.version,
            from_status='published',
            to_status='rolled_back',
            reason=reason,
            operated_by=user.id
        )
        db.session.add(rh)

        pq = PrintQueue(
            label_id=new_version.id,
            store=new_version.store,
            sku=new_version.sku,
            original_price=new_version.original_price,
            promotion_price=new_version.promotion_price,
            effective_from=new_version.effective_from,
            effective_to=new_version.effective_to,
            template=new_version.template
        )
        db.session.add(pq)

        _mark_handover_conflict_on_label_change(label.id, '已被回滚', user.id)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': '回滚成功，已生成新版本',
            'data': {
                'rolled_back_label_id': label.id,
                'new_label_id': new_version.id,
                'new_version': new_version.version
            }
        })

    else:
        label.status = 'rolled_back'
        label.rolled_back_at = now
        label.rolled_back_by = user.id
        label.rollback_reason = reason

        rh = RollbackHistory(
            label_id=label.id,
            from_version=label.version,
            to_version=label.version,
            from_status='published',
            to_status='rolled_back',
            reason=reason,
            operated_by=user.id
        )
        db.session.add(rh)
        _mark_handover_conflict_on_label_change(label.id, '已被回滚', user.id)
        db.session.commit()

        return jsonify({'success': True, 'message': '回滚成功'})


@app.route('/api/labels/<int:label_id>/revoke', methods=['POST'])
@require_roles('admin')
def revoke_label(label_id):
    data = request.get_json() or {}
    reason = (data.get('reason') or '').strip()
    if not reason:
        return jsonify({'success': False, 'message': '撤销原因不能为空'}), 400

    label = PriceLabel.query.get(label_id)
    if not label:
        return jsonify({'success': False, 'message': '价签不存在'}), 404

    if label.status != 'published':
        return jsonify({'success': False, 'message': '只有已发布状态才能撤销发布'}), 400

    printed_items = PrintQueue.query.filter(
        PrintQueue.label_id == label_id,
        PrintQueue.status == 'printed'
    ).all()
    if printed_items:
        return jsonify({
            'success': False,
            'message': '该价签已有已打印记录，不能直接撤销。请先记录线下处理原因，联系门店回收已打印价签后再操作。',
            'code': 'PRINTED_EXISTS'
        }), 400

    user = g.current_user
    now = datetime.utcnow()
    original_status = label.status

    pending_items = PrintQueue.query.filter(
        PrintQueue.label_id == label_id,
        PrintQueue.status == 'pending'
    ).all()
    affected_ids = []
    for pq in pending_items:
        affected_ids.append(pq.id)
        db.session.delete(pq)

    label.status = 'revoked'
    label.revoked_at = now
    label.revoked_by = user.id
    label.revoke_reason = reason

    rev_log = RevocationLog(
        label_id=label.id,
        sku=label.sku,
        store=label.store,
        original_status=original_status,
        reason=reason,
        operated_by=user.id,
        affected_print_queue_ids=','.join(str(i) for i in affected_ids) if affected_ids else ''
    )
    db.session.add(rev_log)
    _mark_handover_conflict_on_label_change(label.id, '已被撤销发布', user.id)
    db.session.commit()

    return jsonify({
        'success': True,
        'message': '发布撤销成功',
        'data': {
            'label_id': label.id,
            'revoked_at': now.isoformat(),
            'affected_print_queue_count': len(affected_ids)
        }
    })


# ==================== 撤销申请接口 ====================
@app.route('/api/labels/revoke-request', methods=['POST'])
@require_roles('admin', 'operator')
def submit_revocation_requests():
    data = request.get_json() or {}
    label_ids = data.get('label_ids', [])
    reason = (data.get('reason') or '').strip()

    if not label_ids:
        return jsonify({'success': False, 'message': '未选择价签'}), 400
    if not reason:
        return jsonify({'success': False, 'message': '撤销原因不能为空'}), 400

    user = g.current_user
    now = datetime.utcnow()
    success_count = 0
    failed = []
    created_requests = []

    for lid in label_ids:
        label = PriceLabel.query.get(lid)
        if not label:
            failed.append({'id': lid, 'reason': '价签不存在'})
            continue

        if label.status not in ('published', 'revoking'):
            failed.append({'id': lid, 'reason': f'状态为{label.status}，只有已发布价签可申请撤销'})
            continue

        existing = RevocationRequest.query.filter(
            RevocationRequest.label_id == lid,
            RevocationRequest.status == 'pending'
        ).first()
        if existing:
            failed.append({'id': lid, 'reason': '已有撤销申请处理中，不能重复提交'})
            continue

        original_status = label.status

        if label.status == 'published':
            label.status = 'revoking'

        pending_items = PrintQueue.query.filter(
            PrintQueue.label_id == lid,
            PrintQueue.status == 'pending'
        ).all()
        affected_ids = [pq.id for pq in pending_items]

        req = RevocationRequest(
            label_id=lid,
            sku=label.sku,
            store=label.store,
            original_status=original_status,
            reason=reason,
            status='pending',
            requested_by=user.id,
            requested_at=now,
            affected_print_queue_ids=','.join(str(i) for i in affected_ids) if affected_ids else ''
        )
        db.session.add(req)
        db.session.flush()

        log = RevocationRequestLog(
            request_id=req.id,
            label_id=lid,
            sku=label.sku,
            store=label.store,
            action='submit',
            original_status=original_status,
            reason=reason,
            operated_by=user.id,
            created_at=now,
            affected_print_queue_ids=','.join(str(i) for i in affected_ids) if affected_ids else ''
        )
        db.session.add(log)

        created_requests.append({
            'request_id': req.id,
            'label_id': lid,
            'sku': label.sku,
            'store': label.store
        })
        success_count += 1

    db.session.commit()

    return jsonify({
        'success': True,
        'data': {
            'success_count': success_count,
            'failed': failed,
            'requests': created_requests
        }
    })


@app.route('/api/revocation-requests', methods=['GET'])
@require_login
def list_revocation_requests():
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 20, type=int)
    status = request.args.get('status', '')
    sku = request.args.get('sku', '')
    store = request.args.get('store', '')

    query = RevocationRequest.query
    if status:
        query = query.filter_by(status=status)
    if sku:
        query = query.filter(RevocationRequest.sku.like(f'%{sku}%'))
    if store:
        query = query.filter(RevocationRequest.store.like(f'%{store}%'))

    total = query.count()
    records = query.order_by(RevocationRequest.requested_at.desc()).offset((page - 1) * size).limit(size).all()

    result_list = []
    for r in records:
        d = r.to_dict()
        d['requested_by_name'] = _get_username(r.requested_by)
        d['reviewed_by_name'] = _get_username(r.reviewed_by)
        result_list.append(d)

    return jsonify({
        'success': True,
        'data': {'list': result_list, 'total': total}
    })


@app.route('/api/revocation-requests/<int:request_id>', methods=['GET'])
@require_login
def get_revocation_request_detail(request_id):
    req = RevocationRequest.query.get(request_id)
    if not req:
        return jsonify({'success': False, 'message': '申请不存在'}), 404

    logs = RevocationRequestLog.query.filter_by(request_id=request_id).order_by(RevocationRequestLog.created_at.desc()).all()

    d = req.to_dict()
    d['requested_by_name'] = _get_username(req.requested_by)
    d['reviewed_by_name'] = _get_username(req.reviewed_by)

    log_list = []
    for log in logs:
        ld = log.to_dict()
        ld['operated_by_name'] = _get_username(log.operated_by)
        log_list.append(ld)

    return jsonify({
        'success': True,
        'data': {
            'request': d,
            'logs': log_list
        }
    })


@app.route('/api/revocation-requests/<int:request_id>/review', methods=['POST'])
@require_roles('admin')
def review_revocation_request(request_id):
    data = request.get_json() or {}
    approve = data.get('approve', True)
    comment = (data.get('comment') or '').strip()
    offline_note = (data.get('offline_processing_note') or '').strip()

    req = RevocationRequest.query.get(request_id)
    if not req:
        return jsonify({'success': False, 'message': '申请不存在'}), 404
    if req.status != 'pending':
        return jsonify({'success': False, 'message': f'申请状态为{req.status}，无法审批'}), 400

    label = PriceLabel.query.get(req.label_id)
    if not label:
        return jsonify({'success': False, 'message': '价签不存在'}), 404

    user = g.current_user
    now = datetime.utcnow()

    if approve:
        printed_items = PrintQueue.query.filter(
            PrintQueue.label_id == req.label_id,
            PrintQueue.status == 'printed'
        ).all()
        if printed_items and not offline_note:
            return jsonify({
                'success': False,
                'message': '该价签已有已打印记录，批准撤销前请填写线下处理说明（回收、销毁等处理方式）',
                'code': 'PRINTED_EXISTS'
            }), 400

        pending_items = PrintQueue.query.filter(
            PrintQueue.label_id == req.label_id,
            PrintQueue.status == 'pending'
        ).all()
        affected_ids = [pq.id for pq in pending_items]
        for pq in pending_items:
            db.session.delete(pq)

        label.status = 'revoked'
        label.revoked_at = now
        label.revoked_by = user.id
        label.revoke_reason = req.reason

        req.status = 'approved'
        req.reviewed_by = user.id
        req.reviewed_at = now
        req.review_comment = comment
        req.offline_processing_note = offline_note if offline_note else None
        req.affected_print_queue_ids = ','.join(str(i) for i in affected_ids) if affected_ids else req.affected_print_queue_ids

        rev_log = RevocationLog(
            label_id=label.id,
            sku=label.sku,
            store=label.store,
            original_status='published',
            reason=req.reason,
            operated_by=user.id,
            affected_print_queue_ids=','.join(str(i) for i in affected_ids) if affected_ids else ''
        )
        db.session.add(rev_log)

        action_log = RevocationRequestLog(
            request_id=req.id,
            label_id=req.label_id,
            sku=req.sku,
            store=req.store,
            action='approve',
            original_status='revoking',
            reason=comment,
            operated_by=user.id,
            created_at=now,
            affected_print_queue_ids=','.join(str(i) for i in affected_ids) if affected_ids else ''
        )
        db.session.add(action_log)
        _mark_handover_conflict_on_label_change(label.id, '已被撤销发布(审批通过)', user.id)

    else:
        if not comment:
            return jsonify({'success': False, 'message': '驳回必须填写处理意见'}), 400

        if label.status == 'revoking':
            label.status = 'published'

        req.status = 'rejected'
        req.reviewed_by = user.id
        req.reviewed_at = now
        req.review_comment = comment

        action_log = RevocationRequestLog(
            request_id=req.id,
            label_id=req.label_id,
            sku=req.sku,
            store=req.store,
            action='reject',
            original_status='revoking',
            reason=comment,
            operated_by=user.id,
            created_at=now
        )
        db.session.add(action_log)

    db.session.commit()

    return jsonify({
        'success': True,
        'message': '审批成功',
        'data': {
            'request_id': req.id,
            'status': req.status
        }
    })


@app.route('/api/revocation-request-logs', methods=['GET'])
@require_login
def list_revocation_request_logs():
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 20, type=int)
    sku = request.args.get('sku', '')
    store = request.args.get('store', '')
    action = request.args.get('action', '')

    query = RevocationRequestLog.query
    if sku:
        query = query.filter(RevocationRequestLog.sku.like(f'%{sku}%'))
    if store:
        query = query.filter(RevocationRequestLog.store.like(f'%{store}%'))
    if action:
        query = query.filter_by(action=action)

    total = query.count()
    records = query.order_by(RevocationRequestLog.created_at.desc()).offset((page - 1) * size).limit(size).all()

    result_list = []
    for r in records:
        d = r.to_dict()
        d['operated_by_name'] = _get_username(r.operated_by)
        result_list.append(d)

    return jsonify({
        'success': True,
        'data': {'list': result_list, 'total': total}
    })


# ==================== 打印清单接口 ====================
@app.route('/api/print-queue', methods=['GET'])
@require_login
def list_print_queue():
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 50, type=int)
    status = request.args.get('status', '')
    store = request.args.get('store', '')

    query = PrintQueue.query.join(PriceLabel, PrintQueue.label_id == PriceLabel.id).filter(
        PriceLabel.status != 'revoking'
    )
    if status:
        query = query.filter(PrintQueue.status == status)
    if store:
        query = query.filter(PrintQueue.store.like(f'%{store}%'))

    total = query.count()
    items = query.order_by(PrintQueue.created_at.desc()).offset((page - 1) * size).limit(size).all()

    return jsonify({
        'success': True,
        'data': {'list': [i.to_dict() for i in items], 'total': total}
    })


@app.route('/api/print-queue/mark-printed', methods=['POST'])
@require_roles('admin', 'operator', 'clerk')
def mark_printed():
    data = request.get_json() or {}
    ids = data.get('ids', [])
    user = g.current_user
    now = datetime.utcnow()

    count = 0
    for pid in ids:
        pq = PrintQueue.query.get(pid)
        if pq and pq.status == 'pending':
            pq.status = 'printed'
            pq.printed_at = now
            pq.printed_by = user.id
            count += 1

    db.session.commit()
    return jsonify({'success': True, 'data': {'count': count}})


# ==================== 回滚历史接口 ====================
@app.route('/api/rollback-history', methods=['GET'])
@require_login
def list_rollback_history():
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 20, type=int)
    sku = request.args.get('sku', '')
    store = request.args.get('store', '')

    query = RollbackHistory.query.join(PriceLabel, RollbackHistory.label_id == PriceLabel.id)
    if sku:
        query = query.filter(PriceLabel.sku.like(f'%{sku}%'))
    if store:
        query = query.filter(PriceLabel.store.like(f'%{store}%'))

    total = query.count()
    records = query.order_by(RollbackHistory.created_at.desc()).offset((page - 1) * size).limit(size).all()

    return jsonify({
        'success': True,
        'data': {'list': [r.to_dict() for r in records], 'total': total}
    })


# ==================== 撤销日志接口 ====================
@app.route('/api/revocation-logs', methods=['GET'])
@require_login
def list_revocation_logs():
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 20, type=int)
    sku = request.args.get('sku', '')
    store = request.args.get('store', '')

    query = RevocationLog.query
    if sku:
        query = query.filter(RevocationLog.sku.like(f'%{sku}%'))
    if store:
        query = query.filter(RevocationLog.store.like(f'%{store}%'))

    total = query.count()
    records = query.order_by(RevocationLog.created_at.desc()).offset((page - 1) * size).limit(size).all()

    result_list = []
    for r in records:
        d = r.to_dict()
        d['operated_by_name'] = _get_username(r.operated_by)
        result_list.append(d)

    return jsonify({
        'success': True,
        'data': {'list': result_list, 'total': total}
    })


# ==================== 导出接口 ====================
def _get_username(user_id):
    if not user_id:
        return ''
    u = User.query.get(user_id)
    return u.username if u else ''


@app.route('/api/export/labels', methods=['GET'])
@require_login
def export_labels():
    status = request.args.get('status', '')
    sku = request.args.get('sku', '')
    store = request.args.get('store', '')

    query = PriceLabel.query
    if status:
        query = query.filter_by(status=status)
    if sku:
        query = query.filter(PriceLabel.sku.like(f'%{sku}%'))
    if store:
        query = query.filter(PriceLabel.store.like(f'%{store}%'))

    labels = query.order_by(PriceLabel.store, PriceLabel.sku, PriceLabel.version).all()

    status_map = {
        'draft': '草稿',
        'pending_approval': '待审',
        'published': '已发布',
        'revoking': '撤销中',
        'rolled_back': '已回滚',
        'revoked': '已撤销'
    }

    rows = []
    for l in labels:
        rows.append({
            'ID': l.id,
            '版本号': l.version,
            'SKU': l.sku,
            '门店': l.store,
            '原价': l.original_price,
            '促销价': l.promotion_price,
            '折扣率': f'{(l.promotion_price / l.original_price * 100):.1f}%' if l.original_price > 0 else '-',
            '生效开始时间': l.effective_from.strftime('%Y-%m-%d %H:%M:%S'),
            '生效结束时间': l.effective_to.strftime('%Y-%m-%d %H:%M:%S'),
            '模板': l.template,
            '状态': status_map.get(l.status, l.status),
            '创建人': _get_username(l.created_by),
            '创建时间': l.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            '提交时间': l.submitted_at.strftime('%Y-%m-%d %H:%M:%S') if l.submitted_at else '',
            '审批人': _get_username(l.approved_by),
            '审批时间': l.approved_at.strftime('%Y-%m-%d %H:%M:%S') if l.approved_at else '',
            '发布人': _get_username(l.published_by),
            '发布时间': l.published_at.strftime('%Y-%m-%d %H:%M:%S') if l.published_at else '',
            '是否回滚': '是' if l.status == 'rolled_back' else '否',
            '回滚人': _get_username(l.rolled_back_by),
            '回滚时间': l.rolled_back_at.strftime('%Y-%m-%d %H:%M:%S') if l.rolled_back_at else '',
            '回滚原因': l.rollback_reason or '',
            '是否撤销': '是' if l.status == 'revoked' else '否',
            '撤销人': _get_username(l.revoked_by),
            '撤销时间': l.revoked_at.strftime('%Y-%m-%d %H:%M:%S') if l.revoked_at else '',
            '撤销原因': l.revoke_reason or '',
            '上一版本ID': l.previous_version_id or '',
            '关联批次ID': l.batch_id or '',
        })

    columns = ['ID', '版本号', 'SKU', '门店', '原价', '促销价', '折扣率', '生效开始时间', '生效结束时间', '模板', '状态', '创建人', '创建时间', '提交时间', '审批人', '审批时间', '发布人', '发布时间', '是否回滚', '回滚人', '回滚时间', '回滚原因', '是否撤销', '撤销人', '撤销时间', '撤销原因', '上一版本ID', '关联批次ID']
    df = pd.DataFrame(rows, columns=columns)
    output = StringIO()
    df.to_csv(output, index=False, encoding='utf-8-sig', lineterminator='\n')
    output.seek(0)

    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = f'attachment; filename=labels_{datetime.now().strftime("%Y%m%d%H%M%S")}.csv'
    return resp


@app.route('/api/export/print-queue', methods=['GET'])
@require_login
def export_print_queue():
    status = request.args.get('status', '')
    store = request.args.get('store', '')

    query = PrintQueue.query.join(PriceLabel, PrintQueue.label_id == PriceLabel.id).filter(
        PriceLabel.status != 'revoking'
    )
    if status:
        query = query.filter(PrintQueue.status == status)
    if store:
        query = query.filter(PrintQueue.store.like(f'%{store}%'))

    items = query.order_by(PrintQueue.created_at.desc()).all()

    rows = []
    for i in items:
        rows.append({
            'ID': i.id,
            '价签ID': i.label_id,
            'SKU': i.sku,
            '门店': i.store,
            '原价': i.original_price,
            '促销价': i.promotion_price,
            '生效开始时间': i.effective_from.strftime('%Y-%m-%d %H:%M:%S'),
            '生效结束时间': i.effective_to.strftime('%Y-%m-%d %H:%M:%S'),
            '模板': i.template,
            '状态': '已打印' if i.status == 'printed' else '待打印',
            '创建时间': i.created_at.strftime('%Y-%m-%d %H:%M:%S')
        })

    columns = ['ID', '价签ID', 'SKU', '门店', '原价', '促销价', '生效开始时间', '生效结束时间', '模板', '状态', '创建时间']
    df = pd.DataFrame(rows, columns=columns)
    output = StringIO()
    df.to_csv(output, index=False, encoding='utf-8-sig', lineterminator='\n')
    output.seek(0)

    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = f'attachment; filename=print_queue_{datetime.now().strftime("%Y%m%d%H%M%S")}.csv'
    return resp


@app.route('/api/export/rollback-history', methods=['GET'])
@require_login
def export_rollback_history():
    sku = request.args.get('sku', '')
    store = request.args.get('store', '')

    query = RollbackHistory.query.join(PriceLabel, RollbackHistory.label_id == PriceLabel.id)
    if sku:
        query = query.filter(PriceLabel.sku.like(f'%{sku}%'))
    if store:
        query = query.filter(PriceLabel.store.like(f'%{store}%'))

    records = query.order_by(RollbackHistory.created_at.desc()).all()

    status_map = {
        'draft': '草稿',
        'pending_approval': '待审',
        'published': '已发布',
        'revoking': '撤销中',
        'rolled_back': '已回滚',
        'revoked': '已撤销'
    }

    rows = []
    for r in records:
        rows.append({
            '记录ID': r.id,
            '价签ID': r.label_id,
            'SKU': r.label.sku if r.label else '',
            '门店': r.label.store if r.label else '',
            '从版本': r.from_version,
            '到版本': r.to_version,
            '从状态': status_map.get(r.from_status, r.from_status or ''),
            '到状态': status_map.get(r.to_status, r.to_status or ''),
            '回滚方式': '回滚到历史版本' if r.from_version != r.to_version else '直接标记回滚',
            '回滚原因': r.reason or '',
            '操作人': _get_username(r.operated_by),
            '操作时间': r.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        })

    columns = ['记录ID', '价签ID', 'SKU', '门店', '从版本', '到版本', '从状态', '到状态', '回滚方式', '回滚原因', '操作人', '操作时间']
    df = pd.DataFrame(rows, columns=columns)
    output = StringIO()
    df.to_csv(output, index=False, encoding='utf-8-sig', lineterminator='\n')
    output.seek(0)

    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = f'attachment; filename=rollback_history_{datetime.now().strftime("%Y%m%d%H%M%S")}.csv'
    return resp


@app.route('/api/export/revocation-logs', methods=['GET'])
@require_login
def export_revocation_logs():
    sku = request.args.get('sku', '')
    store = request.args.get('store', '')

    query = RevocationLog.query
    if sku:
        query = query.filter(RevocationLog.sku.like(f'%{sku}%'))
    if store:
        query = query.filter(RevocationLog.store.like(f'%{store}%'))

    records = query.order_by(RevocationLog.created_at.desc()).all()

    status_map = {
        'draft': '草稿',
        'pending_approval': '待审',
        'published': '已发布',
        'revoking': '撤销中',
        'rolled_back': '已回滚',
        'revoked': '已撤销'
    }

    rows = []
    for r in records:
        rows.append({
            '记录ID': r.id,
            '价签ID': r.label_id,
            'SKU': r.sku,
            '门店': r.store,
            '原状态': status_map.get(r.original_status, r.original_status or ''),
            '撤销原因': r.reason or '',
            '操作人': _get_username(r.operated_by),
            '操作时间': r.created_at.strftime('%Y-%m-%d %H:%M:%S') if r.created_at else '',
            '受影响打印清单ID': r.affected_print_queue_ids or '',
        })

    columns = ['记录ID', '价签ID', 'SKU', '门店', '原状态', '撤销原因', '操作人', '操作时间', '受影响打印清单ID']
    df = pd.DataFrame(rows, columns=columns)
    output = StringIO()
    df.to_csv(output, index=False, encoding='utf-8-sig', lineterminator='\n')
    output.seek(0)

    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = f'attachment; filename=revocation_logs_{datetime.now().strftime("%Y%m%d%H%M%S")}.csv'
    return resp


@app.route('/api/export/revocation-requests', methods=['GET'])
@require_login
def export_revocation_requests():
    status = request.args.get('status', '')
    sku = request.args.get('sku', '')
    store = request.args.get('store', '')

    query = RevocationRequest.query
    if status:
        query = query.filter_by(status=status)
    if sku:
        query = query.filter(RevocationRequest.sku.like(f'%{sku}%'))
    if store:
        query = query.filter(RevocationRequest.store.like(f'%{store}%'))

    records = query.order_by(RevocationRequest.requested_at.desc()).all()

    status_map = {
        'pending': '撤销中',
        'approved': '已批准',
        'rejected': '已驳回'
    }

    label_status_map = {
        'draft': '草稿',
        'pending_approval': '待审',
        'published': '已发布',
        'revoking': '撤销中',
        'rolled_back': '已回滚',
        'revoked': '已撤销'
    }

    rows = []
    for r in records:
        rows.append({
            '申请ID': r.id,
            '价签ID': r.label_id,
            'SKU': r.sku,
            '门店': r.store,
            '申请时状态': label_status_map.get(r.original_status, r.original_status or ''),
            '申请原因': r.reason or '',
            '申请状态': status_map.get(r.status, r.status or ''),
            '线下处理说明': r.offline_processing_note or '',
            '申请人': _get_username(r.requested_by),
            '申请时间': r.requested_at.strftime('%Y-%m-%d %H:%M:%S') if r.requested_at else '',
            '审批人': _get_username(r.reviewed_by),
            '审批时间': r.reviewed_at.strftime('%Y-%m-%d %H:%M:%S') if r.reviewed_at else '',
            '审批意见': r.review_comment or '',
            '受影响打印清单ID': r.affected_print_queue_ids or '',
        })

    columns = ['申请ID', '价签ID', 'SKU', '门店', '申请时状态', '申请原因', '申请状态', '线下处理说明', '申请人', '申请时间', '审批人', '审批时间', '审批意见', '受影响打印清单ID']
    df = pd.DataFrame(rows, columns=columns)
    output = StringIO()
    df.to_csv(output, index=False, encoding='utf-8-sig', lineterminator='\n')
    output.seek(0)

    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = f'attachment; filename=revocation_requests_{datetime.now().strftime("%Y%m%d%H%M%S")}.csv'
    return resp


@app.route('/api/export/revocation-request-logs', methods=['GET'])
@require_login
def export_revocation_request_logs():
    sku = request.args.get('sku', '')
    store = request.args.get('store', '')
    action = request.args.get('action', '')

    query = RevocationRequestLog.query
    if sku:
        query = query.filter(RevocationRequestLog.sku.like(f'%{sku}%'))
    if store:
        query = query.filter(RevocationRequestLog.store.like(f'%{store}%'))
    if action:
        query = query.filter_by(action=action)

    records = query.order_by(RevocationRequestLog.created_at.desc()).all()

    action_map = {
        'submit': '提交申请',
        'approve': '批准撤销',
        'reject': '驳回申请'
    }

    label_status_map = {
        'draft': '草稿',
        'pending_approval': '待审',
        'published': '已发布',
        'revoking': '撤销中',
        'rolled_back': '已回滚',
        'revoked': '已撤销'
    }

    rows = []
    for r in records:
        rows.append({
            '记录ID': r.id,
            '申请ID': r.request_id,
            '价签ID': r.label_id,
            'SKU': r.sku,
            '门店': r.store,
            '操作类型': action_map.get(r.action, r.action or ''),
            '原状态': label_status_map.get(r.original_status, r.original_status or ''),
            '原因/意见': r.reason or '',
            '操作人': _get_username(r.operated_by),
            '操作时间': r.created_at.strftime('%Y-%m-%d %H:%M:%S') if r.created_at else '',
            '受影响打印清单ID': r.affected_print_queue_ids or '',
        })

    columns = ['记录ID', '申请ID', '价签ID', 'SKU', '门店', '操作类型', '原状态', '原因/意见', '操作人', '操作时间', '受影响打印清单ID']
    df = pd.DataFrame(rows, columns=columns)
    output = StringIO()
    df.to_csv(output, index=False, encoding='utf-8-sig', lineterminator='\n')
    output.seek(0)

    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = f'attachment; filename=revocation_request_logs_{datetime.now().strftime("%Y%m%d%H%M%S")}.csv'
    return resp


# ==================== 交接单接口 ====================
HANDOVER_STATUS_MAP = {
    'pending': '待签收',
    'signed': '已签收',
    'voided': '已作废',
}


def _recalc_handover_conflict(sheet_id):
    sheet = HandoverSheet.query.get(sheet_id)
    if not sheet:
        return
    has_any_conflict = False
    for item in sheet.items:
        label = PriceLabel.query.get(item.label_id)
        if not label or label.status in ('revoked', 'rolled_back'):
            item.is_conflict = True
            reasons = []
            if not label:
                item.conflict_reason = '价签已被删除'
            else:
                if label.status == 'revoked':
                    reasons.append('价签已被撤销')
                if label.status == 'rolled_back':
                    reasons.append('价签已被回滚')
                if label.version != item.snapshot_label_version:
                    reasons.append(f'价签版本已变更(v{item.snapshot_label_version}→v{label.version})')
                item.conflict_reason = '；'.join(reasons) if reasons else None
            has_any_conflict = True
        elif label.version != item.snapshot_label_version:
            item.is_conflict = True
            item.conflict_reason = f'价签版本已变更(v{item.snapshot_label_version}→v{label.version})'
            has_any_conflict = True
        else:
            item.is_conflict = False
            item.conflict_reason = None
    sheet.has_conflict = has_any_conflict
    sheet.conflict_checked_at = datetime.utcnow()


def _mark_handover_conflict_on_label_change(label_id, change_description, operated_by_user_id):
    affected_items = HandoverItem.query.filter_by(label_id=label_id).join(HandoverSheet).filter(
        HandoverSheet.status.in_(['pending', 'signed'])
    ).all()
    if not affected_items:
        return
    now = datetime.utcnow()
    for item in affected_items:
        item.is_conflict = True
        existing_reason = item.conflict_reason or ''
        new_reason = change_description
        item.conflict_reason = f'{existing_reason}；{new_reason}' if existing_reason else new_reason
        item.sheet.has_conflict = True
        item.sheet.conflict_checked_at = now

        log = HandoverLog(
            sheet_id=item.sheet_id,
            sheet_no=item.sheet.sheet_no,
            action='conflict_auto_mark',
            detail=f'价签{change_description}，自动标记冲突(价签ID:{label_id})',
            operated_by=operated_by_user_id,
            created_at=now,
        )
        db.session.add(log)


@app.route('/api/handover-sheets', methods=['GET'])
@require_login
def list_handover_sheets():
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 20, type=int)
    status = request.args.get('status', '')
    store = request.args.get('store', '')
    sheet_no = request.args.get('sheet_no', '')
    has_conflict = request.args.get('has_conflict', '')

    query = HandoverSheet.query
    if status:
        query = query.filter_by(status=status)
    if store:
        query = query.filter(HandoverSheet.store.like(f'%{store}%'))
    if sheet_no:
        query = query.filter(HandoverSheet.sheet_no.like(f'%{sheet_no}%'))
    if has_conflict and has_conflict.lower() == 'true':
        query = query.filter_by(has_conflict=True)

    total = query.count()
    records = query.order_by(HandoverSheet.created_at.desc()).offset((page - 1) * size).limit(size).all()

    result_list = []
    for r in records:
        d = r.to_dict()
        d['created_by_name'] = _get_username(r.created_by)
        d['signed_by_name'] = _get_username(r.signed_by)
        d['voided_by_name'] = _get_username(r.voided_by)
        result_list.append(d)

    return jsonify({
        'success': True,
        'data': {'list': result_list, 'total': total}
    })


@app.route('/api/handover-sheets/<int:sheet_id>', methods=['GET'])
@require_login
def get_handover_sheet_detail(sheet_id):
    sheet = HandoverSheet.query.get(sheet_id)
    if not sheet:
        return jsonify({'success': False, 'message': '交接单不存在'}), 404

    _recalc_handover_conflict(sheet_id)
    db.session.commit()

    d = sheet.to_dict(include_items=True)
    d['created_by_name'] = _get_username(sheet.created_by)
    d['signed_by_name'] = _get_username(sheet.signed_by)
    d['voided_by_name'] = _get_username(sheet.voided_by)

    logs = HandoverLog.query.filter_by(sheet_id=sheet_id).order_by(HandoverLog.created_at.desc()).all()
    d['logs'] = [log.to_dict() for log in logs]
    for log_entry in d['logs']:
        log_entry['operated_by_name'] = _get_username(log_entry['operated_by'])

    return jsonify({'success': True, 'data': d})


@app.route('/api/handover-sheets', methods=['POST'])
@require_roles('admin', 'operator')
def create_handover_sheet():
    data = request.get_json() or {}
    title = (data.get('title') or '').strip()
    store = (data.get('store') or '').strip()
    remark = (data.get('remark') or '').strip()
    label_ids = data.get('label_ids', [])

    if not title:
        return jsonify({'success': False, 'message': '交接单标题不能为空'}), 400
    if not store:
        return jsonify({'success': False, 'message': '门店不能为空'}), 400
    if not label_ids:
        return jsonify({'success': False, 'message': '请选择至少一个价签'}), 400

    user = g.current_user
    now = datetime.utcnow()

    valid_labels = []
    failed = []
    seen_ids = set()

    for lid in label_ids:
        if lid in seen_ids:
            failed.append({'id': lid, 'reason': '重复添加同一价签'})
            continue
        seen_ids.add(lid)

        label = PriceLabel.query.get(lid)
        if not label:
            failed.append({'id': lid, 'reason': '价签不存在'})
            continue
        if label.status not in ('published',):
            failed.append({'id': lid, 'reason': f'价签状态为{label.status}，只有已发布价签可加入交接单'})
            continue
        if label.store != store:
            failed.append({'id': lid, 'reason': f'价签门店"{label.store}"与交接单门店"{store}"不一致'})
            continue

        existing = HandoverItem.query.filter_by(label_id=lid).join(HandoverSheet).filter(
            HandoverSheet.status.in_(['pending', 'signed'])
        ).first()
        if existing:
            failed.append({'id': lid, 'reason': f'该价签已在交接单 {existing.sheet.sheet_no} 中，不可重复加入'})
            continue

        valid_labels.append(label)

    if not valid_labels:
        return jsonify({'success': False, 'message': '没有可添加的有效价签', 'data': {'failed': failed}}), 400

    sheet_no = f'HO{now.strftime("%Y%m%d%H%M%S")}{uuid.uuid4().hex[:6].upper()}'
    sheet = HandoverSheet(
        sheet_no=sheet_no,
        title=title,
        store=store,
        status='pending',
        total_items=len(valid_labels),
        remark=remark or None,
        created_by=user.id,
        created_at=now,
    )
    db.session.add(sheet)
    db.session.flush()

    items = []
    for label in valid_labels:
        item = HandoverItem(
            sheet_id=sheet.id,
            label_id=label.id,
            snapshot_sku=label.sku,
            snapshot_store=label.store,
            snapshot_original_price=label.original_price,
            snapshot_promotion_price=label.promotion_price,
            snapshot_effective_from=label.effective_from,
            snapshot_effective_to=label.effective_to,
            snapshot_template=label.template,
            snapshot_label_status=label.status,
            snapshot_label_version=label.version,
            print_status='pending',
        )
        db.session.add(item)
        items.append(item)

    log = HandoverLog(
        sheet_id=sheet.id,
        sheet_no=sheet_no,
        action='create',
        detail=f'创建交接单，含{len(valid_labels)}项价签' + (f'，{len(failed)}项被拒绝' if failed else ''),
        operated_by=user.id,
        created_at=now,
    )
    db.session.add(log)
    db.session.commit()

    return jsonify({
        'success': True,
        'data': {
            'sheet_id': sheet.id,
            'sheet_no': sheet_no,
            'total_items': len(valid_labels),
            'failed': failed,
        }
    })


@app.route('/api/handover-sheets/<int:sheet_id>/sign', methods=['POST'])
@require_roles('admin', 'operator', 'clerk')
def sign_handover_sheet(sheet_id):
    data = request.get_json() or {}
    sheet = HandoverSheet.query.get(sheet_id)
    if not sheet:
        return jsonify({'success': False, 'message': '交接单不存在'}), 404

    if sheet.status != 'pending':
        return jsonify({'success': False, 'message': f'交接单状态为{HANDOVER_STATUS_MAP.get(sheet.status, sheet.status)}，无法签收'}), 400

    user = g.current_user
    now = datetime.utcnow()

    conflict_items = HandoverItem.query.filter_by(sheet_id=sheet_id, is_conflict=True).count()
    if conflict_items > 0:
        return jsonify({
            'success': False,
            'message': f'交接单中有{conflict_items}项冲突项，请先处理冲突后再签收',
            'code': 'CONFLICT_EXISTS',
        }), 400

    sheet.status = 'signed'
    sheet.signed_by = user.id
    sheet.signed_at = now

    for item in sheet.items:
        item.print_status = 'printed'

    log = HandoverLog(
        sheet_id=sheet.id,
        sheet_no=sheet.sheet_no,
        action='sign',
        detail=f'签收交接单，签收人: {user.username}',
        operated_by=user.id,
        created_at=now,
    )
    db.session.add(log)
    db.session.commit()

    return jsonify({'success': True, 'message': '签收成功', 'data': {'sheet_id': sheet.id, 'signed_at': now.isoformat()}})


@app.route('/api/handover-sheets/<int:sheet_id>/void', methods=['POST'])
@require_roles('admin')
def void_handover_sheet(sheet_id):
    data = request.get_json() or {}
    void_reason = (data.get('reason') or '').strip()
    if not void_reason:
        return jsonify({'success': False, 'message': '作废原因不能为空'}), 400

    sheet = HandoverSheet.query.get(sheet_id)
    if not sheet:
        return jsonify({'success': False, 'message': '交接单不存在'}), 404

    if sheet.status == 'voided':
        return jsonify({'success': False, 'message': '交接单已作废，不能重复操作'}), 400

    user = g.current_user
    now = datetime.utcnow()
    original_status = sheet.status

    sheet.status = 'voided'
    sheet.voided_by = user.id
    sheet.voided_at = now
    sheet.void_reason = void_reason

    log = HandoverLog(
        sheet_id=sheet.id,
        sheet_no=sheet.sheet_no,
        action='void',
        detail=f'作废交接单(原状态: {HANDOVER_STATUS_MAP.get(original_status, original_status)})，原因: {void_reason}',
        operated_by=user.id,
        created_at=now,
    )
    db.session.add(log)
    db.session.commit()

    return jsonify({'success': True, 'message': '作废成功', 'data': {'sheet_id': sheet.id}})


@app.route('/api/handover-sheets/<int:sheet_id>/check-conflicts', methods=['POST'])
@require_login
def check_handover_conflicts(sheet_id):
    sheet = HandoverSheet.query.get(sheet_id)
    if not sheet:
        return jsonify({'success': False, 'message': '交接单不存在'}), 404

    _recalc_handover_conflict(sheet_id)
    db.session.commit()

    conflict_items = [item.to_dict() for item in sheet.items if item.is_conflict]

    user = g.current_user
    log = HandoverLog(
        sheet_id=sheet.id,
        sheet_no=sheet.sheet_no,
        action='check_conflict',
        detail=f'检查冲突，发现{len(conflict_items)}项冲突',
        operated_by=user.id,
    )
    db.session.add(log)
    db.session.commit()

    return jsonify({
        'success': True,
        'data': {
            'sheet_id': sheet.id,
            'has_conflict': sheet.has_conflict,
            'conflict_count': len(conflict_items),
            'conflict_items': conflict_items,
        }
    })


@app.route('/api/handover-sheets/available-labels', methods=['GET'])
@require_roles('admin', 'operator')
def get_available_labels_for_handover():
    store = request.args.get('store', '')
    query = PriceLabel.query.filter_by(status='published')
    if store:
        query = query.filter_by(store=store)

    labels = query.order_by(PriceLabel.store, PriceLabel.sku).all()

    result_list = []
    for label in labels:
        in_active_sheet = HandoverItem.query.filter_by(label_id=label.id).join(HandoverSheet).filter(
            HandoverSheet.status.in_(['pending', 'signed'])
        ).first()

        result_list.append({
            'id': label.id,
            'sku': label.sku,
            'store': label.store,
            'original_price': label.original_price,
            'promotion_price': label.promotion_price,
            'effective_from': label.effective_from.isoformat(),
            'effective_to': label.effective_to.isoformat(),
            'template': label.template,
            'version': label.version,
            'in_active_sheet': in_active_sheet is not None,
            'active_sheet_no': in_active_sheet.sheet.sheet_no if in_active_sheet else None,
        })

    return jsonify({'success': True, 'data': result_list})


@app.route('/api/handover-logs', methods=['GET'])
@require_login
def list_handover_logs():
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 20, type=int)
    sheet_no = request.args.get('sheet_no', '')
    action = request.args.get('action', '')
    operated_by = request.args.get('operated_by', '', type=int)

    query = HandoverLog.query
    if sheet_no:
        query = query.filter(HandoverLog.sheet_no.like(f'%{sheet_no}%'))
    if action:
        query = query.filter_by(action=action)
    if operated_by:
        query = query.filter_by(operated_by=operated_by)

    total = query.count()
    records = query.order_by(HandoverLog.created_at.desc()).offset((page - 1) * size).limit(size).all()

    result_list = []
    for r in records:
        d = r.to_dict()
        d['operated_by_name'] = _get_username(r.operated_by)
        result_list.append(d)

    return jsonify({
        'success': True,
        'data': {'list': result_list, 'total': total}
    })


@app.route('/api/export/handover-sheets', methods=['GET'])
@require_login
def export_handover_sheets():
    status = request.args.get('status', '')
    store = request.args.get('store', '')

    query = HandoverSheet.query
    if status:
        query = query.filter_by(status=status)
    if store:
        query = query.filter(HandoverSheet.store.like(f'%{store}%'))

    records = query.order_by(HandoverSheet.created_at.desc()).all()

    rows = []
    for r in records:
        rows.append({
            'ID': r.id,
            '交接单号': r.sheet_no,
            '标题': r.title,
            '门店': r.store,
            '状态': HANDOVER_STATUS_MAP.get(r.status, r.status),
            '价签数量': r.total_items,
            '有冲突': '是' if r.has_conflict else '否',
            '备注': r.remark or '',
            '创建人': _get_username(r.created_by),
            '创建时间': r.created_at.strftime('%Y-%m-%d %H:%M:%S') if r.created_at else '',
            '签收人': _get_username(r.signed_by),
            '签收时间': r.signed_at.strftime('%Y-%m-%d %H:%M:%S') if r.signed_at else '',
            '作废人': _get_username(r.voided_by),
            '作废时间': r.voided_at.strftime('%Y-%m-%d %H:%M:%S') if r.voided_at else '',
            '作废原因': r.void_reason or '',
        })

    columns = ['ID', '交接单号', '标题', '门店', '状态', '价签数量', '有冲突', '备注', '创建人', '创建时间', '签收人', '签收时间', '作废人', '作废时间', '作废原因']
    df = pd.DataFrame(rows, columns=columns)
    output = StringIO()
    df.to_csv(output, index=False, encoding='utf-8-sig', lineterminator='\n')
    output.seek(0)

    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = f'attachment; filename=handover_sheets_{datetime.now().strftime("%Y%m%d%H%M%S")}.csv'
    return resp


@app.route('/api/export/handover-sheet/<int:sheet_id>', methods=['GET'])
@require_login
def export_handover_sheet_detail(sheet_id):
    sheet = HandoverSheet.query.get(sheet_id)
    if not sheet:
        return jsonify({'success': False, 'message': '交接单不存在'}), 404

    rows = []
    for idx, item in enumerate(sheet.items, 1):
        rows.append({
            '序号': idx,
            '价签ID': item.label_id,
            'SKU': item.snapshot_sku,
            '门店': item.snapshot_store,
            '原价': item.snapshot_original_price,
            '促销价': item.snapshot_promotion_price,
            '折扣率': f'{(item.snapshot_promotion_price / item.snapshot_original_price * 100):.1f}%' if item.snapshot_original_price > 0 else '-',
            '生效开始时间': item.snapshot_effective_from.strftime('%Y-%m-%d %H:%M:%S') if item.snapshot_effective_from else '',
            '生效结束时间': item.snapshot_effective_to.strftime('%Y-%m-%d %H:%M:%S') if item.snapshot_effective_to else '',
            '模板': item.snapshot_template,
            '快照状态': item.snapshot_label_status,
            '快照版本': f'v{item.snapshot_label_version}',
            '打印状态': '已打印' if item.print_status == 'printed' else '待打印',
            '冲突': '是' if item.is_conflict else '否',
            '冲突原因': item.conflict_reason or '',
            '当前价签状态': item.label.status if item.label else '已删除',
        })

    columns = ['序号', '价签ID', 'SKU', '门店', '原价', '促销价', '折扣率', '生效开始时间', '生效结束时间', '模板', '快照状态', '快照版本', '打印状态', '冲突', '冲突原因', '当前价签状态']
    df = pd.DataFrame(rows, columns=columns)
    output = StringIO()
    df.to_csv(output, index=False, encoding='utf-8-sig', lineterminator='\n')
    output.seek(0)

    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = f'attachment; filename=handover_{sheet.sheet_no}_{datetime.now().strftime("%Y%m%d%H%M%S")}.csv'
    return resp


@app.route('/api/export/handover-logs', methods=['GET'])
@require_login
def export_handover_logs():
    sheet_no = request.args.get('sheet_no', '')
    action = request.args.get('action', '')

    query = HandoverLog.query
    if sheet_no:
        query = query.filter(HandoverLog.sheet_no.like(f'%{sheet_no}%'))
    if action:
        query = query.filter_by(action=action)

    records = query.order_by(HandoverLog.created_at.desc()).all()

    action_cn = {
        'create': '创建',
        'sign': '签收',
        'void': '作废',
        'check_conflict': '冲突检查',
        'conflict_auto_mark': '冲突自动标记',
    }

    rows = []
    for r in records:
        rows.append({
            '记录ID': r.id,
            '交接单ID': r.sheet_id,
            '交接单号': r.sheet_no,
            '操作类型': action_cn.get(r.action, r.action),
            '操作详情': r.detail or '',
            '操作人': _get_username(r.operated_by),
            '操作时间': r.created_at.strftime('%Y-%m-%d %H:%M:%S') if r.created_at else '',
        })

    columns = ['记录ID', '交接单ID', '交接单号', '操作类型', '操作详情', '操作人', '操作时间']
    df = pd.DataFrame(rows, columns=columns)
    output = StringIO()
    df.to_csv(output, index=False, encoding='utf-8-sig', lineterminator='\n')
    output.seek(0)

    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = f'attachment; filename=handover_logs_{datetime.now().strftime("%Y%m%d%H%M%S")}.csv'
    return resp


# ==================== 统计接口 ====================
@app.route('/api/stats/overview', methods=['GET'])
@require_login
def stats_overview():
    total = PriceLabel.query.count()
    draft = PriceLabel.query.filter_by(status='draft').count()
    pending = PriceLabel.query.filter_by(status='pending_approval').count()
    published = PriceLabel.query.filter_by(status='published').count()
    revoking = PriceLabel.query.filter_by(status='revoking').count()
    rolled_back = PriceLabel.query.filter_by(status='rolled_back').count()
    revoked = PriceLabel.query.filter_by(status='revoked').count()
    pending_print = PrintQueue.query.filter_by(status='pending').count()
    rollback_count = RollbackHistory.query.count()
    revocation_count = RevocationLog.query.count()
    revocation_request_count = RevocationRequest.query.count()
    revocation_request_pending = RevocationRequest.query.filter_by(status='pending').count()
    handover_pending = HandoverSheet.query.filter_by(status='pending').count()
    handover_signed = HandoverSheet.query.filter_by(status='signed').count()
    handover_voided = HandoverSheet.query.filter_by(status='voided').count()
    handover_conflict = HandoverSheet.query.filter_by(has_conflict=True).count()

    return jsonify({
        'success': True,
        'data': {
            'total': total,
            'draft': draft,
            'pending_approval': pending,
            'published': published,
            'revoking': revoking,
            'rolled_back': rolled_back,
            'revoked': revoked,
            'pending_print': pending_print,
            'rollback_count': rollback_count,
            'revocation_count': revocation_count,
            'revocation_request_count': revocation_request_count,
            'revocation_request_pending': revocation_request_pending,
            'handover_pending': handover_pending,
            'handover_signed': handover_signed,
            'handover_voided': handover_voided,
            'handover_conflict': handover_conflict,
            'in_publish_window': is_in_publish_window()[0]
        }
    })


# ==================== 启动 ====================
with app.app_context():
    init_default_data()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
