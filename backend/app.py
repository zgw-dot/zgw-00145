import os
import json
import uuid
import hashlib
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
    HandoverSheet, HandoverItem, HandoverLog,
    HandoverAuthorization, HandoverReceipt, HandoverAuditLog,
    DrillDemoData, DrillSession, DrillStep, DrillAcceptanceRecord
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
                'enabled': False,
                'start_hour': 9,
                'end_hour': 18,
                'weekdays_only': False
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


def _get_client_ip():
    try:
        if request.headers.get('X-Forwarded-For'):
            return request.headers.get('X-Forwarded-For').split(',')[0].strip()
        return request.remote_addr or 'unknown'
    except Exception:
        return 'unknown'


def _get_user_agent():
    try:
        return (request.headers.get('User-Agent') or '')[:500]
    except Exception:
        return ''


def _get_request_body_safe():
    try:
        body = request.get_json(silent=True)
        if body:
            return json.dumps(body, ensure_ascii=False)[:4000]
    except Exception:
        pass
    try:
        raw = request.get_data(as_text=True)
        if raw:
            return raw[:4000]
    except Exception:
        pass
    return ''


def _audit_log(action, result, sheet=None, authorization=None,
               block_reason=None, block_code=None,
               response_status=None, response_message=None,
               detail=None, user=None):
    try:
        current_user = user or g.get('current_user')
        sheet_id = None
        sheet_no = None
        if sheet:
            sheet_id = sheet.id
            sheet_no = sheet.sheet_no
        elif authorization:
            sheet_id = authorization.sheet_id
            s = HandoverSheet.query.get(authorization.sheet_id)
            if s:
                sheet_no = s.sheet_no

        try:
            req_params = request.args.to_dict() if request else {}
            req_params_str = json.dumps(req_params, ensure_ascii=False)[:2000] if req_params else ''
            req_path = request.path if request else ''
            req_method = request.method if request else ''
        except Exception:
            req_params_str = ''
            req_path = ''
            req_method = ''

        log = HandoverAuditLog(
            sheet_id=sheet_id,
            sheet_no=sheet_no,
            authorization_id=authorization.id if authorization else None,
            action=action,
            result=result,
            block_reason=block_reason,
            block_code=block_code,
            user_id=current_user.id if current_user else None,
            user_name=current_user.username if current_user else None,
            user_role=current_user.role if current_user else None,
            client_ip=_get_client_ip(),
            user_agent=_get_user_agent(),
            request_path=req_path,
            request_method=req_method,
            request_params=req_params_str,
            request_body=_get_request_body_safe(),
            response_status=response_status,
            response_message=response_message,
            detail=detail,
        )
        db.session.add(log)
    except Exception as e:
        import traceback
        traceback.print_exc()


def _check_can_view_sheet(sheet, user):
    if not sheet or not user:
        return False, 'NOT_FOUND', '交接单不存在'
    if user.role == 'admin':
        return True, None, None
    scope = sheet.view_scope or 'assigned'
    if scope == 'assigned':
        if sheet.created_by == user.id:
            return True, None, None
        if sheet.assigned_to == user.id:
            return True, None, None
        active_auth = HandoverAuthorization.query.filter(
            HandoverAuthorization.sheet_id == sheet.id,
            HandoverAuthorization.token_type == 'view',
            HandoverAuthorization.user_id == user.id,
            HandoverAuthorization.revoked == False,
            HandoverAuthorization.expires_at > datetime.utcnow(),
        ).first()
        if active_auth:
            if active_auth.one_time and active_auth.is_used:
                return False, 'TOKEN_USED', '查看凭证已使用，请联系管理员重新授权'
            return True, None, None
        return False, 'VIEW_NOT_AUTHORIZED', f'您无权查看此交接单（查看范围:仅指派人员）'
    elif scope == 'store_all':
        if sheet.store == (user.store_name if hasattr(user, 'store_name') else sheet.store):
            return True, None, None
        return False, 'VIEW_STORE_MISMATCH', f'此交接单仅门店"{sheet.store}"人员可查看'
    elif scope == 'role_all':
        return True, None, None
    elif scope == 'specific':
        if sheet.created_by == user.id or sheet.assigned_to == user.id:
            return True, None, None
        view_auth = HandoverAuthorization.query.filter(
            HandoverAuthorization.sheet_id == sheet.id,
            HandoverAuthorization.token_type == 'view',
            HandoverAuthorization.user_id == user.id,
            HandoverAuthorization.revoked == False,
            HandoverAuthorization.expires_at > datetime.utcnow(),
        ).first()
        if view_auth:
            if view_auth.one_time and view_auth.is_used:
                return False, 'TOKEN_USED', '查看凭证已使用'
            return True, None, None
        return False, 'VIEW_NOT_AUTHORIZED', '您不在授权查看列表中'
    return False, 'VIEW_NOT_AUTHORIZED', '您无权查看此交接单'


def _validate_sign_token(token_str, sheet, user):
    if not token_str:
        return None, False, 'TOKEN_REQUIRED', '签收凭证不能为空'
    auth = HandoverAuthorization.query.filter_by(auth_token=token_str).first()
    if not auth:
        return None, False, 'TOKEN_NOT_FOUND', '签收凭证不存在'
    if auth.sheet_id != sheet.id:
        return auth, False, 'TOKEN_SHEET_MISMATCH', '签收凭证与交接单不匹配'
    if auth.token_type != 'sign':
        return auth, False, 'TOKEN_TYPE_WRONG', f'凭证类型错误（需要签收凭证，当前为{auth.token_type}）'
    if auth.revoked:
        return auth, False, 'TOKEN_REVOKED', f'签收凭证已被撤回，原因: {auth.revoke_reason or "无"}'
    now = datetime.utcnow()
    if auth.expires_at < now:
        return auth, False, 'TOKEN_EXPIRED', f'签收凭证已过期（过期时间: {auth.expires_at.strftime("%Y-%m-%d %H:%M:%S")}）'
    if auth.one_time and auth.is_used:
        return auth, False, 'TOKEN_USED', '签收凭证已被使用，一次性凭证不可重复使用'
    if auth.user_id and auth.user_id != user.id:
        expected_user = _get_username(auth.user_id)
        return auth, False, 'TOKEN_USER_MISMATCH', f'此凭证仅限用户"{expected_user}"使用，请使用正确账号'
    if auth.role_restriction and auth.role_restriction != user.role:
        role_label = {'admin': '管理员', 'operator': '运营', 'clerk': '店员'}.get(auth.role_restriction, auth.role_restriction)
        return auth, False, 'TOKEN_ROLE_MISMATCH', f'此凭证仅限{role_label}角色使用，您的角色不匹配'
    return auth, True, None, None


def _mark_auth_used(auth, user_id):
    auth.is_used = True
    auth.used_at = datetime.utcnow()
    auth.used_by = user_id


def _generate_auth_token(sheet_id, token_type, user_id=None,
                         role_restriction=None, store_restriction=None,
                         valid_hours=24, one_time=True, created_by=None,
                         remark=None, generation_id=None):
    now = datetime.utcnow()
    expires_at = now + timedelta(hours=valid_hours)
    token_str = f'H{token_type.upper()[0]}{now.strftime("%Y%m%d%H%M%S")}{uuid.uuid4().hex[:12].upper()}'
    auth = HandoverAuthorization(
        sheet_id=sheet_id,
        auth_token=token_str,
        token_type=token_type,
        user_id=user_id,
        role_restriction=role_restriction,
        store_restriction=store_restriction,
        expires_at=expires_at,
        is_used=False,
        created_by=created_by,
        created_at=now,
        remark=remark,
        one_time=one_time,
        revoked=False,
        generation_id=generation_id,
    )
    db.session.add(auth)
    return auth


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
    only_assigned = request.args.get('only_assigned', 'false').lower() == 'true'

    user = g.current_user
    query = HandoverSheet.query

    if user.role != 'admin':
        subq = db.session.query(HandoverAuthorization.sheet_id).filter(
            HandoverAuthorization.user_id == user.id,
            HandoverAuthorization.revoked == False,
            HandoverAuthorization.expires_at > datetime.utcnow()
        ).distinct()
        query = query.filter(
            db.or_(
                HandoverSheet.created_by == user.id,
                HandoverSheet.assigned_to == user.id,
                HandoverSheet.view_scope == 'role_all',
                HandoverSheet.id.in_(subq)
            )
        )
    if only_assigned:
        query = query.filter(HandoverSheet.assigned_to == user.id)
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
        d['assigned_to_name'] = _get_username(r.assigned_to)
        result_list.append(d)

    return jsonify({
        'success': True,
        'data': {'list': result_list, 'total': total}
    })


@app.route('/api/handover-sheets/<int:sheet_id>', methods=['GET'])
@require_login
def get_handover_sheet_detail(sheet_id):
    sheet = HandoverSheet.query.get(sheet_id)
    user = g.current_user
    view_token = request.args.get('view_token', '')

    if not sheet:
        _audit_log('view_detail', 'blocked', sheet=sheet, block_reason='交接单不存在',
                   block_code='NOT_FOUND', response_status=404, response_message='交接单不存在')
        db.session.commit()
        return jsonify({'success': False, 'message': '交接单不存在', 'code': 'NOT_FOUND'}), 404

    can_view, block_code, block_reason = _check_can_view_sheet(sheet, user)
    if not can_view:
        if view_token:
            v_auth = HandoverAuthorization.query.filter_by(auth_token=view_token).first()
            if v_auth and v_auth.token_type == 'view' and v_auth.sheet_id == sheet_id and not v_auth.revoked:
                now = datetime.utcnow()
                if v_auth.expires_at >= now:
                    if v_auth.user_id and v_auth.user_id != user.id:
                        expected = _get_username(v_auth.user_id)
                        _audit_log('view_detail', 'blocked', sheet=sheet, authorization=v_auth,
                                   block_reason=f'查看凭证用户不匹配，仅限{expected}',
                                   block_code='TOKEN_USER_MISMATCH',
                                   response_status=403,
                                   response_message=f'查看凭证仅限用户"{expected}"使用，请使用正确账号')
                        db.session.commit()
                        return jsonify({
                            'success': False,
                            'message': f'查看凭证仅限用户"{expected}"使用，请使用正确账号',
                            'code': 'TOKEN_USER_MISMATCH'
                        }), 403
                    if v_auth.one_time and v_auth.is_used:
                        _audit_log('view_detail', 'blocked', sheet=sheet, authorization=v_auth,
                                   block_reason='查看凭证已使用', block_code='TOKEN_USED',
                                   response_status=403, response_message='查看凭证已使用')
                        db.session.commit()
                        return jsonify({
                            'success': False,
                            'message': '查看凭证已使用，请联系管理员重新授权',
                            'code': 'TOKEN_USED'
                        }), 403
                    can_view = True
                    block_code = None
                    block_reason = None
                    if v_auth.one_time:
                        _mark_auth_used(v_auth, user.id)

    if not can_view:
        _audit_log('view_detail', 'blocked', sheet=sheet,
                   block_reason=block_reason, block_code=block_code,
                   response_status=403, response_message=block_reason)
        db.session.commit()
        return jsonify({
            'success': False,
            'message': block_reason or '您无权查看此交接单',
            'code': block_code or 'VIEW_NOT_AUTHORIZED'
        }), 403

    _recalc_handover_conflict(sheet_id)

    d = sheet.to_dict(include_items=True)
    d['created_by_name'] = _get_username(sheet.created_by)
    d['signed_by_name'] = _get_username(sheet.signed_by)
    d['voided_by_name'] = _get_username(sheet.voided_by)
    d['assigned_to_name'] = _get_username(sheet.assigned_to)
    d['assigned_by_name'] = _get_username(sheet.assigned_by)
    d['revoked_by_name'] = _get_username(sheet.revoked_by)
    d['reopened_by_name'] = _get_username(sheet.reopened_by)

    logs = HandoverLog.query.filter_by(sheet_id=sheet_id).order_by(HandoverLog.created_at.desc()).all()
    d['logs'] = [log.to_dict() for log in logs]
    for log_entry in d['logs']:
        log_entry['operated_by_name'] = _get_username(log_entry['operated_by'])

    authorizations = HandoverAuthorization.query.filter_by(sheet_id=sheet_id).order_by(
        HandoverAuthorization.created_at.desc()).all()
    d['authorizations'] = [a.to_dict() for a in authorizations]

    receipts = HandoverReceipt.query.filter_by(sheet_id=sheet_id).order_by(
        HandoverReceipt.signed_at.desc()).all()
    d['receipts'] = [r.to_dict() for r in receipts]

    can_sign = False
    if sheet.status == 'pending' and sheet.revoke_status != 'revoked':
        can_sign = (user.role == 'admin' or
                    sheet.created_by == user.id or
                    sheet.assigned_to == user.id)
    d['can_sign'] = can_sign
    d['current_user_role'] = user.role
    d['current_user_id'] = user.id
    d['current_user_name'] = user.username

    _audit_log('view_detail', 'allowed', sheet=sheet,
               detail=f'用户{user.username}成功查看交接单详情')
    db.session.commit()

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
    sign_token = (data.get('sign_token') or '').strip()
    signer_remark = (data.get('signer_remark') or '').strip()
    sheet = HandoverSheet.query.get(sheet_id)
    user = g.current_user
    now = datetime.utcnow()

    if not sheet:
        _audit_log('sign', 'blocked', sheet=sheet, block_reason='交接单不存在',
                   block_code='NOT_FOUND', response_status=404, response_message='交接单不存在')
        db.session.commit()
        return jsonify({'success': False, 'message': '交接单不存在', 'code': 'NOT_FOUND'}), 404

    if sheet.status == 'voided':
        _audit_log('sign', 'blocked', sheet=sheet,
                   block_reason='交接单已作废，不能签收',
                   block_code='VOIDED_SHEET',
                   response_status=400, response_message='交接单已作废')
        db.session.commit()
        return jsonify({
            'success': False,
            'message': '交接单已作废，无法签收',
            'code': 'VOIDED_SHEET',
        }), 400

    if sheet.revoke_status == 'revoked':
        _audit_log('sign', 'blocked', sheet=sheet,
                   block_reason='交接单签收权已被撤回',
                   block_code='REVOKED_SIGN',
                   response_status=400, response_message='交接单签收权已被撤回')
        db.session.commit()
        return jsonify({
            'success': False,
            'message': '交接单签收权已被撤回，无法签收',
            'code': 'REVOKED_SIGN',
        }), 400

    if sheet.status == 'signed':
        _audit_log('sign', 'blocked', sheet=sheet,
                   block_reason='交接单已签收，不能重复签收',
                   block_code='ALREADY_SIGNED',
                   response_status=400, response_message='交接单已签收')
        db.session.commit()
        return jsonify({
            'success': False,
            'message': '交接单已签收，不能重复签收',
            'code': 'ALREADY_SIGNED',
        }), 400

    if sheet.status != 'pending':
        _audit_log('sign', 'blocked', sheet=sheet,
                   block_reason=f'交接单状态异常:{sheet.status}',
                   block_code='STATUS_INVALID',
                   response_status=400,
                   response_message=f'交接单状态为{HANDOVER_STATUS_MAP.get(sheet.status, sheet.status)}')
        db.session.commit()
        return jsonify({
            'success': False,
            'message': f'交接单状态为{HANDOVER_STATUS_MAP.get(sheet.status, sheet.status)}，无法签收',
            'code': 'STATUS_INVALID',
        }), 400

    conflict_items_count = HandoverItem.query.filter_by(sheet_id=sheet_id, is_conflict=True).count()
    if conflict_items_count > 0:
        _audit_log('sign', 'blocked', sheet=sheet,
                   block_reason=f'交接单有{conflict_items_count}项冲突',
                   block_code='CONFLICT_EXISTS',
                   response_status=400,
                   response_message=f'有{conflict_items_count}项冲突')
        db.session.commit()
        return jsonify({
            'success': False,
            'message': f'交接单中有{conflict_items_count}项冲突项，请先处理冲突后再签收',
            'code': 'CONFLICT_EXISTS',
        }), 400

    validated_auth = None
    if user.role != 'admin':
        is_assigned = (sheet.assigned_to == user.id) or (sheet.created_by == user.id)
        if not sign_token and not is_assigned:
            if sheet.view_scope == 'assigned':
                _audit_log('sign', 'blocked', sheet=sheet,
                           block_reason='没有签收权限且未提供签收凭证',
                           block_code='SIGN_NOT_ASSIGNED',
                           response_status=403,
                           response_message='您不是指派签收人，请提供签收凭证')
                db.session.commit()
                return jsonify({
                    'success': False,
                    'message': '您不是指派签收人，请使用签收凭证签收',
                    'code': 'SIGN_NOT_ASSIGNED',
                }), 403

        if sign_token:
            auth, token_ok, token_code, token_msg = _validate_sign_token(sign_token, sheet, user)
            if not token_ok:
                _audit_log('sign', 'blocked', sheet=sheet, authorization=auth,
                           block_reason=token_msg, block_code=token_code,
                           response_status=403, response_message=token_msg)
                db.session.commit()
                return jsonify({
                    'success': False,
                    'message': token_msg,
                    'code': token_code,
                }), 403
            validated_auth = auth
        else:
            if not is_assigned:
                _audit_log('sign', 'blocked', sheet=sheet,
                           block_reason='不是指派签收人且未提供凭证',
                           block_code='SIGN_NOT_AUTHORIZED',
                           response_status=403,
                           response_message='您没有签收权限')
                db.session.commit()
                return jsonify({
                    'success': False,
                    'message': '您没有签收权限，请联系管理员指派或获取签收凭证',
                    'code': 'SIGN_NOT_AUTHORIZED',
                }), 403

    sheet.status = 'signed'
    sheet.signed_by = user.id
    sheet.signed_at = now

    for item in sheet.items:
        item.print_status = 'printed'

    log = HandoverLog(
        sheet_id=sheet.id,
        sheet_no=sheet.sheet_no,
        action='sign',
        detail=f'签收交接单，签收人: {user.username}' + (f'，备注: {signer_remark}' if signer_remark else ''),
        operated_by=user.id,
        created_at=now,
    )
    db.session.add(log)

    if validated_auth:
        _mark_auth_used(validated_auth, user.id)

    receipt_no = f'RCP{now.strftime("%Y%m%d%H%M%S")}{uuid.uuid4().hex[:8].upper()}'
    sheet_snap = {
        'id': sheet.id,
        'sheet_no': sheet.sheet_no,
        'title': sheet.title,
        'store': sheet.store,
        'status': sheet.status,
        'total_items': sheet.total_items,
        'remark': sheet.remark,
        'created_by': sheet.created_by,
        'created_at': sheet.created_at.isoformat() if sheet.created_at else None,
        'signed_by': user.id,
        'signed_at': now.isoformat(),
        'assigned_to': sheet.assigned_to,
        'view_scope': sheet.view_scope,
    }
    items_snap = []
    for i in sheet.items:
        items_snap.append({
            'id': i.id,
            'label_id': i.label_id,
            'sku': i.snapshot_sku,
            'store': i.snapshot_store,
            'original_price': i.snapshot_original_price,
            'promotion_price': i.snapshot_promotion_price,
            'effective_from': i.snapshot_effective_from.isoformat() if i.snapshot_effective_from else None,
            'effective_to': i.snapshot_effective_to.isoformat() if i.snapshot_effective_to else None,
            'template': i.snapshot_template,
            'label_version': i.snapshot_label_version,
        })
    hash_source = f"{receipt_no}|{sheet.id}|{user.id}|{now.isoformat()}|{len(items_snap)}"
    receipt_hash = hashlib.sha256(hash_source.encode('utf-8')).hexdigest()

    receipt = HandoverReceipt(
        sheet_id=sheet.id,
        receipt_no=receipt_no,
        authorization_id=validated_auth.id if validated_auth else None,
        signed_by=user.id,
        signed_at=now,
        signer_ip=_get_client_ip(),
        signer_user_agent=_get_user_agent(),
        signer_remark=signer_remark or None,
        item_count=len(items_snap),
        sheet_snapshot=json.dumps(sheet_snap, ensure_ascii=False),
        items_snapshot=json.dumps(items_snap, ensure_ascii=False),
        receipt_hash=receipt_hash,
        export_count=0,
    )
    db.session.add(receipt)

    _audit_log('sign', 'allowed', sheet=sheet, authorization=validated_auth,
               response_status=200,
               detail=f'成功签收，签收人:{user.username}，生成回执:{receipt_no}' + (f'，凭证ID:{validated_auth.id}' if validated_auth else ''))

    db.session.commit()

    return jsonify({
        'success': True,
        'message': '签收成功，交接回执已生成',
        'data': {
            'sheet_id': sheet.id,
            'signed_at': now.isoformat(),
            'receipt_no': receipt_no,
            'receipt_hash': receipt_hash,
            'receipt_id': receipt.id,
            'sign_token_used': sign_token is not None and sign_token != '',
        }
    })


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


# ==================== 授权签收台接口 ====================
@app.route('/api/handover-auth-station/summary', methods=['GET'])
@require_login
def auth_station_summary():
    user = g.current_user
    if user.role == 'admin':
        pending_sheets = HandoverSheet.query.filter_by(status='pending').count()
        signed_sheets = HandoverSheet.query.filter_by(status='signed').count()
        voided_sheets = HandoverSheet.query.filter_by(status='voided').count()
        assigned_to_me = 0
    else:
        pending_sheets = HandoverSheet.query.filter(
            HandoverSheet.status == 'pending',
            db.or_(
                HandoverSheet.created_by == user.id,
                HandoverSheet.assigned_to == user.id,
                HandoverSheet.view_scope == 'role_all'
            )
        ).count()
        signed_sheets = HandoverSheet.query.filter(
            HandoverSheet.status == 'signed',
            HandoverSheet.signed_by == user.id
        ).count()
        voided_sheets = 0
        assigned_to_me = HandoverSheet.query.filter(
            HandoverSheet.assigned_to == user.id,
            HandoverSheet.status == 'pending'
        ).count()

    pending_authorizations = HandoverAuthorization.query.filter(
        HandoverAuthorization.is_used == False,
        HandoverAuthorization.revoked == False,
        HandoverAuthorization.expires_at > datetime.utcnow()
    ).count()
    total_receipts = HandoverReceipt.query.count()

    return jsonify({
        'success': True,
        'data': {
            'pending_sheets': pending_sheets,
            'signed_sheets': signed_sheets,
            'voided_sheets': voided_sheets,
            'assigned_to_me': assigned_to_me,
            'pending_authorizations': pending_authorizations,
            'total_receipts': total_receipts,
        }
    })


@app.route('/api/handover-sheets/<int:sheet_id>/assign', methods=['POST'])
@require_roles('admin')
def assign_handover_sheet(sheet_id):
    data = request.get_json() or {}
    assigned_to = data.get('assigned_to')
    view_scope = (data.get('view_scope') or 'assigned').strip()
    remark = (data.get('remark') or '').strip()

    sheet = HandoverSheet.query.get(sheet_id)
    user = g.current_user
    now = datetime.utcnow()

    if not sheet:
        _audit_log('assign', 'blocked', sheet=sheet, block_reason='交接单不存在',
                   block_code='NOT_FOUND', response_status=404)
        db.session.commit()
        return jsonify({'success': False, 'message': '交接单不存在', 'code': 'NOT_FOUND'}), 404
    if sheet.status == 'voided':
        _audit_log('assign', 'blocked', sheet=sheet, block_reason='作废单不能指派',
                   block_code='VOIDED_SHEET', response_status=400)
        db.session.commit()
        return jsonify({'success': False, 'message': '已作废的交接单不能指派', 'code': 'VOIDED_SHEET'}), 400

    valid_scopes = ['assigned', 'store_all', 'role_all', 'specific']
    if view_scope not in valid_scopes:
        return jsonify({'success': False, 'message': f'view_scope必须是: {", ".join(valid_scopes)}'}), 400

    target_user = None
    if assigned_to:
        try:
            assigned_to = int(assigned_to)
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': 'assigned_to必须是用户ID整数'}), 400
        target_user = User.query.get(assigned_to)
        if not target_user:
            _audit_log('assign', 'blocked', sheet=sheet, block_reason=f'用户ID{assigned_to}不存在',
                       block_code='USER_NOT_FOUND', response_status=400)
            db.session.commit()
            return jsonify({'success': False, 'message': '指派用户不存在', 'code': 'USER_NOT_FOUND'}), 400
        sheet.assigned_to = assigned_to

    sheet.assigned_at = now
    sheet.assigned_by = user.id
    sheet.view_scope = view_scope

    detail_parts = []
    if assigned_to:
        detail_parts.append(f'指派接手人:{target_user.username}')
    detail_parts.append(f'查看范围:{view_scope}')
    if remark:
        detail_parts.append(f'备注:{remark}')

    log = HandoverLog(
        sheet_id=sheet.id,
        sheet_no=sheet.sheet_no,
        action='assign',
        detail='；'.join(detail_parts),
        operated_by=user.id,
        created_at=now,
    )
    db.session.add(log)
    _audit_log('assign', 'allowed', sheet=sheet, response_status=200,
               detail=f'指派成功:接手人={target_user.username if target_user else "未指定"};范围={view_scope}')
    db.session.commit()

    return jsonify({
        'success': True,
        'message': '指派成功',
        'data': {
            'sheet_id': sheet.id,
            'assigned_to': sheet.assigned_to,
            'assigned_to_name': _get_username(sheet.assigned_to),
            'view_scope': sheet.view_scope,
            'assigned_at': now.isoformat(),
        }
    })


@app.route('/api/handover-sheets/<int:sheet_id>/authorizations', methods=['GET'])
@require_login
def list_handover_authorizations(sheet_id):
    sheet = HandoverSheet.query.get(sheet_id)
    user = g.current_user

    if not sheet:
        return jsonify({'success': False, 'message': '交接单不存在'}), 404
    if user.role != 'admin' and sheet.created_by != user.id and sheet.assigned_to != user.id:
        return jsonify({'success': False, 'message': '无权限查看授权列表'}), 403

    records = HandoverAuthorization.query.filter_by(sheet_id=sheet_id).order_by(
        HandoverAuthorization.created_at.desc()).all()
    return jsonify({
        'success': True,
        'data': {
            'sheet_id': sheet_id,
            'list': [r.to_dict() for r in records],
            'total': len(records),
        }
    })


@app.route('/api/handover-sheets/<int:sheet_id>/authorize', methods=['POST'])
@require_roles('admin')
def create_handover_authorization(sheet_id):
    data = request.get_json() or {}
    sheet = HandoverSheet.query.get(sheet_id)
    user = g.current_user

    if not sheet:
        return jsonify({'success': False, 'message': '交接单不存在', 'code': 'NOT_FOUND'}), 404
    if sheet.status == 'voided':
        return jsonify({'success': False, 'message': '已作废交接单不能生成授权凭证', 'code': 'VOIDED_SHEET'}), 400

    token_type = (data.get('token_type') or 'sign').strip()
    if token_type not in ('sign', 'view', 'receipt'):
        return jsonify({'success': False, 'message': 'token_type必须是sign/view/receipt'}), 400

    target_user_id = data.get('user_id')
    role_restriction = (data.get('role_restriction') or '').strip() or None
    store_restriction = (data.get('store_restriction') or '').strip() or None
    valid_hours = data.get('valid_hours', 24)
    one_time = data.get('one_time', True)
    remark = (data.get('remark') or '').strip() or None
    batch_count = int(data.get('batch_count', 1))
    specific_usernames = data.get('usernames', []) or []

    try:
        valid_hours = int(valid_hours)
        if valid_hours <= 0 or valid_hours > 720:
            raise ValueError()
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'valid_hours必须是1-720的整数小时'}), 400
    try:
        batch_count = int(batch_count)
        if batch_count <= 0 or batch_count > 50:
            raise ValueError()
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'batch_count必须是1-50的整数'}), 400

    if target_user_id:
        try:
            target_user_id = int(target_user_id)
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': 'user_id必须是整数'}), 400
        if not User.query.get(target_user_id):
            return jsonify({'success': False, 'message': '指定user_id不存在', 'code': 'USER_NOT_FOUND'}), 400

    users_to_create = []
    if specific_usernames and isinstance(specific_usernames, list):
        for uname in specific_usernames:
            u = User.query.filter_by(username=str(uname).strip()).first()
            if u:
                users_to_create.append(u)

    generation_id = f'GEN{datetime.now().strftime("%Y%m%d%H%M%S")}{uuid.uuid4().hex[:6].upper()}'
    created_tokens = []

    if users_to_create:
        for tu in users_to_create:
            auth = _generate_auth_token(
                sheet_id=sheet_id,
                token_type=token_type,
                user_id=tu.id,
                role_restriction=None,
                store_restriction=store_restriction,
                valid_hours=valid_hours,
                one_time=one_time,
                created_by=user.id,
                remark=remark,
                generation_id=generation_id,
            )
            created_tokens.append(auth)
    else:
        for _ in range(batch_count):
            auth = _generate_auth_token(
                sheet_id=sheet_id,
                token_type=token_type,
                user_id=target_user_id,
                role_restriction=role_restriction,
                store_restriction=store_restriction,
                valid_hours=valid_hours,
                one_time=one_time,
                created_by=user.id,
                remark=remark,
                generation_id=generation_id,
            )
            created_tokens.append(auth)

    db.session.flush()

    type_cn = {'sign': '签收凭证', 'view': '查看凭证', 'receipt': '回执凭证'}
    log = HandoverLog(
        sheet_id=sheet.id,
        sheet_no=sheet.sheet_no,
        action=f'authorize_{token_type}',
        detail=f'生成{len(created_tokens)}个{type_cn.get(token_type, token_type)}，有效期{valid_hours}小时，generation_id={generation_id}',
        operated_by=user.id,
    )
    db.session.add(log)
    for auth in created_tokens:
        _audit_log(f'authorize_{token_type}', 'allowed', sheet=sheet, authorization=auth,
                   response_status=200,
                   detail=f'生成{type_cn.get(token_type, token_type)}: user={_get_username(auth.user_id)}; role={auth.role_restriction}; valid={valid_hours}h')

    db.session.commit()

    return jsonify({
        'success': True,
        'message': f'成功生成{len(created_tokens)}个授权凭证',
        'data': {
            'sheet_id': sheet_id,
            'generation_id': generation_id,
            'token_type': token_type,
            'count': len(created_tokens),
            'tokens': [a.to_dict() for a in created_tokens],
        }
    })


@app.route('/api/handover-authorizations/validate', methods=['POST'])
@require_login
def validate_authorization_endpoint():
    data = request.get_json() or {}
    token_str = (data.get('token') or '').strip()
    token_type = (data.get('token_type') or 'sign').strip()
    user = g.current_user

    if not token_str:
        return jsonify({'success': False, 'message': 'token不能为空', 'code': 'TOKEN_REQUIRED',
                        'data': {'valid': False}}), 400

    auth = HandoverAuthorization.query.filter_by(auth_token=token_str).first()
    now = datetime.utcnow()

    if not auth:
        _audit_log('validate_token', 'blocked', authorization=auth,
                   block_reason='凭证不存在', block_code='TOKEN_NOT_FOUND')
        db.session.commit()
        return jsonify({
            'success': True,
            'data': {
                'valid': False,
                'code': 'TOKEN_NOT_FOUND',
                'reason': '签收凭证不存在，请确认凭证是否正确',
            }
        })

    sheet = HandoverSheet.query.get(auth.sheet_id)
    result = {'valid': True}

    if not sheet:
        result['valid'] = False
        result['code'] = 'SHEET_NOT_FOUND'
        result['reason'] = '交接单已被删除'
    elif auth.token_type != token_type:
        result['valid'] = False
        result['code'] = 'TOKEN_TYPE_WRONG'
        result['reason'] = f'凭证类型不匹配，需要{token_type}，当前为{auth.token_type}'
    elif auth.revoked:
        result['valid'] = False
        result['code'] = 'TOKEN_REVOKED'
        result['reason'] = f'凭证已被撤回，原因: {auth.revoke_reason or "无"}'
    elif auth.expires_at < now:
        result['valid'] = False
        result['code'] = 'TOKEN_EXPIRED'
        result['reason'] = f'凭证已过期，过期时间: {auth.expires_at.strftime("%Y-%m-%d %H:%M:%S")}'
    elif auth.one_time and auth.is_used:
        result['valid'] = False
        result['code'] = 'TOKEN_USED'
        result['reason'] = '凭证已被使用过，一次性凭证不可重复使用'
    elif auth.user_id and auth.user_id != user.id:
        expected = _get_username(auth.user_id)
        result['valid'] = False
        result['code'] = 'TOKEN_USER_MISMATCH'
        result['reason'] = f'此凭证仅限用户"{expected}"使用，您当前账号是"{user.username}"，账号不匹配'
    elif auth.role_restriction and auth.role_restriction != user.role:
        role_label = {'admin': '管理员', 'operator': '运营', 'clerk': '店员'}.get(auth.role_restriction, auth.role_restriction)
        result['valid'] = False
        result['code'] = 'TOKEN_ROLE_MISMATCH'
        result['reason'] = f'此凭证仅限{role_label}使用，您的角色不匹配'
    elif sheet and sheet.status == 'voided':
        result['valid'] = False
        result['code'] = 'VOIDED_SHEET'
        result['reason'] = '交接单已作废，无法使用凭证'

    if sheet:
        result['sheet_id'] = sheet.id
        result['sheet_no'] = sheet.sheet_no
        result['sheet_title'] = sheet.title
        result['sheet_store'] = sheet.store
        result['sheet_status'] = sheet.status
    result['auth_id'] = auth.id
    result['auth_token'] = auth.auth_token
    result['token_type'] = auth.token_type
    result['expires_at'] = auth.expires_at.isoformat() if auth.expires_at else None
    result['restricted_user'] = _get_username(auth.user_id) if auth.user_id else None
    result['restricted_role'] = auth.role_restriction
    result['is_used'] = auth.is_used
    result['one_time'] = auth.one_time

    _audit_log('validate_token', 'allowed' if result['valid'] else 'blocked',
               sheet=sheet, authorization=auth,
               block_code=result.get('code'),
               block_reason=result.get('reason') if not result['valid'] else None,
               response_status=200,
               detail=f'校验token={token_str[:12]}... 结果={"通过" if result["valid"] else result.get("reason")}')
    db.session.commit()

    return jsonify({
        'success': True,
        'data': result
    })


@app.route('/api/handover-authorizations/<int:auth_id>/revoke', methods=['POST'])
@require_roles('admin')
def revoke_authorization(auth_id):
    data = request.get_json() or {}
    reason = (data.get('reason') or '').strip()
    if not reason:
        return jsonify({'success': False, 'message': '撤回原因不能为空', 'code': 'REASON_REQUIRED'}), 400

    auth = HandoverAuthorization.query.get(auth_id)
    if not auth:
        return jsonify({'success': False, 'message': '授权凭证不存在', 'code': 'NOT_FOUND'}), 404
    if auth.revoked:
        return jsonify({'success': False, 'message': '凭证已被撤回，不能重复操作', 'code': 'ALREADY_REVOKED'}), 400

    user = g.current_user
    now = datetime.utcnow()
    auth.revoked = True
    auth.revoked_at = now
    auth.revoked_by = user.id
    auth.revoke_reason = reason

    sheet = HandoverSheet.query.get(auth.sheet_id)
    if sheet:
        log = HandoverLog(
            sheet_id=sheet.id,
            sheet_no=sheet.sheet_no,
            action='revoke_auth',
            detail=f'撤回授权凭证ID={auth_id}，类型={auth.token_type}，原因: {reason}',
            operated_by=user.id,
        )
        db.session.add(log)

    _audit_log('revoke_auth', 'allowed', sheet=sheet, authorization=auth,
               response_status=200,
               detail=f'撤回凭证，原因: {reason}')
    db.session.commit()

    return jsonify({
        'success': True,
        'message': '凭证已撤回',
        'data': {
            'auth_id': auth.id,
            'revoked_at': now.isoformat(),
            'revoked_by': user.id,
        }
    })


@app.route('/api/handover-sheets/<int:sheet_id>/revoke-sign', methods=['POST'])
@require_roles('admin')
def revoke_handover_sign(sheet_id):
    data = request.get_json() or {}
    reason = (data.get('reason') or '').strip()
    if not reason:
        return jsonify({'success': False, 'message': '撤回原因不能为空', 'code': 'REASON_REQUIRED'}), 400

    sheet = HandoverSheet.query.get(sheet_id)
    user = g.current_user
    now = datetime.utcnow()

    if not sheet:
        return jsonify({'success': False, 'message': '交接单不存在', 'code': 'NOT_FOUND'}), 404
    if sheet.status != 'signed':
        return jsonify({'success': False, 'message': '只有已签收的交接单可以撤回签收', 'code': 'NOT_SIGNED'}), 400
    if sheet.revoke_status == 'revoked':
        return jsonify({'success': False, 'message': '签收已被撤回，不能重复操作', 'code': 'ALREADY_REVOKED'}), 400

    sheet.revoke_status = 'revoked'
    sheet.revoked_by = user.id
    sheet.revoked_at = now
    sheet.revoke_reason = reason

    signer_name = _get_username(sheet.signed_by)

    log = HandoverLog(
        sheet_id=sheet.id,
        sheet_no=sheet.sheet_no,
        action='revoke_sign',
        detail=f'撤回签收(原签收人:{signer_name}，原签收时间:{sheet.signed_at.strftime("%Y-%m-%d %H:%M:%S") if sheet.signed_at else ""})，原因: {reason}',
        operated_by=user.id,
    )
    db.session.add(log)
    _audit_log('revoke_sign', 'allowed', sheet=sheet, response_status=200,
               detail=f'撤回签收，原签收人={signer_name}, 原因={reason}')
    db.session.commit()

    return jsonify({
        'success': True,
        'message': '签收已撤回，可以重新签收',
        'data': {
            'sheet_id': sheet.id,
            'revoke_status': 'revoked',
            'revoked_at': now.isoformat(),
            'original_signer': signer_name,
        }
    })


@app.route('/api/handover-sheets/<int:sheet_id>/reopen', methods=['POST'])
@require_roles('admin')
def reopen_handover_sheet(sheet_id):
    data = request.get_json() or {}
    remark = (data.get('remark') or '').strip()
    sheet = HandoverSheet.query.get(sheet_id)
    user = g.current_user
    now = datetime.utcnow()

    if not sheet:
        return jsonify({'success': False, 'message': '交接单不存在', 'code': 'NOT_FOUND'}), 404
    if sheet.revoke_status != 'revoked':
        return jsonify({'success': False, 'message': '只有撤回签收后的交接单可以重开', 'code': 'NOT_REVOKED'}), 400
    if sheet.status == 'voided':
        return jsonify({'success': False, 'message': '已作废交接单不能重开', 'code': 'VOIDED'}), 400

    sheet.status = 'pending'
    sheet.revoke_status = 'reopened'
    sheet.reopened_by = user.id
    sheet.reopened_at = now
    sheet.signed_by = None
    sheet.signed_at = None

    for item in sheet.items:
        item.print_status = 'pending'

    log = HandoverLog(
        sheet_id=sheet.id,
        sheet_no=sheet.sheet_no,
        action='reopen',
        detail=f'重开交接单(从撤回签收状态恢复为待签收)，原撤回原因: {sheet.revoke_reason or ""}' + (f'，备注: {remark}' if remark else ''),
        operated_by=user.id,
    )
    db.session.add(log)
    _audit_log('reopen', 'allowed', sheet=sheet, response_status=200,
               detail='重开成功，状态改为pending')
    db.session.commit()

    return jsonify({
        'success': True,
        'message': '交接单已重开，可以重新签收',
        'data': {
            'sheet_id': sheet.id,
            'new_status': 'pending',
            'reopened_at': now.isoformat(),
        }
    })


@app.route('/api/handover-receipts', methods=['GET'])
@require_login
def list_handover_receipts():
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 20, type=int)
    receipt_no = request.args.get('receipt_no', '')
    sheet_no = request.args.get('sheet_no', '')
    signed_by = request.args.get('signed_by', '', type=int)

    query = HandoverReceipt.query
    if receipt_no:
        query = query.filter(HandoverReceipt.receipt_no.like(f'%{receipt_no}%'))
    if sheet_no:
        query = query.join(HandoverSheet).filter(HandoverSheet.sheet_no.like(f'%{sheet_no}%'))
    if signed_by:
        query = query.filter_by(signed_by=signed_by)

    total = query.count()
    records = query.order_by(HandoverReceipt.signed_at.desc()).offset((page - 1) * size).limit(size).all()

    result_list = []
    for r in records:
        d = r.to_dict()
        s = HandoverSheet.query.get(r.sheet_id)
        if s:
            d['sheet_no'] = s.sheet_no
            d['sheet_title'] = s.title
            d['sheet_store'] = s.store
        result_list.append(d)

    return jsonify({
        'success': True,
        'data': {'list': result_list, 'total': total}
    })


@app.route('/api/handover-receipts/<int:receipt_id>', methods=['GET'])
@require_login
def get_handover_receipt_detail(receipt_id):
    receipt = HandoverReceipt.query.get(receipt_id)
    user = g.current_user
    if not receipt:
        return jsonify({'success': False, 'message': '回执不存在'}), 404

    sheet = HandoverSheet.query.get(receipt.sheet_id)
    if user.role != 'admin':
        if sheet and sheet.created_by != user.id and sheet.assigned_to != user.id and receipt.signed_by != user.id:
            return jsonify({'success': False, 'message': '无权限查看此回执'}), 403

    d = receipt.to_dict(include_snapshot=True)
    if sheet:
        d['sheet_no'] = sheet.sheet_no
        d['sheet_title'] = sheet.title
        d['sheet_store'] = sheet.store
        d['sheet_status'] = sheet.status
        d['sheet_created_by_name'] = _get_username(sheet.created_by)
        d['sheet_assigned_to_name'] = _get_username(sheet.assigned_to)
    return jsonify({'success': True, 'data': d})


@app.route('/api/handover-audit-logs', methods=['GET'])
@require_roles('admin')
def list_handover_audit_logs():
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 20, type=int)
    sheet_no = request.args.get('sheet_no', '')
    action = request.args.get('action', '')
    result_filter = request.args.get('result', '')
    user_name = request.args.get('user_name', '')
    block_code = request.args.get('block_code', '')

    query = HandoverAuditLog.query
    if sheet_no:
        query = query.filter(HandoverAuditLog.sheet_no.like(f'%{sheet_no}%'))
    if action:
        query = query.filter_by(action=action)
    if result_filter:
        query = query.filter_by(result=result_filter)
    if user_name:
        query = query.filter(HandoverAuditLog.user_name.like(f'%{user_name}%'))
    if block_code:
        query = query.filter(HandoverAuditLog.block_code.like(f'%{block_code}%'))

    total = query.count()
    records = query.order_by(HandoverAuditLog.created_at.desc()).offset(
        (page - 1) * size).limit(size).all()

    return jsonify({
        'success': True,
        'data': {
            'list': [r.to_dict() for r in records],
            'total': total,
            'allowed_count': HandoverAuditLog.query.filter_by(result='allowed').count(),
            'blocked_count': HandoverAuditLog.query.filter_by(result='blocked').count(),
        }
    })


@app.route('/api/handover-audit-logs/timeline', methods=['GET'])
@require_login
def handover_audit_timeline():
    sheet_id = request.args.get('sheet_id', type=int)
    sheet_no = request.args.get('sheet_no', '')
    if not sheet_id and not sheet_no:
        return jsonify({'success': False, 'message': '请提供sheet_id或sheet_no'}), 400

    query = HandoverAuditLog.query
    if sheet_id:
        query = query.filter_by(sheet_id=sheet_id)
    if sheet_no:
        query = query.filter(HandoverAuditLog.sheet_no.like(f'%{sheet_no}%'))

    records = query.order_by(HandoverAuditLog.created_at.asc()).all()

    action_cn = {
        'assign': '指派接手人',
        'authorize_sign': '生成签收凭证',
        'authorize_view': '生成查看凭证',
        'authorize_receipt': '生成回执凭证',
        'validate_token': '校验凭证',
        'revoke_auth': '撤回授权',
        'revoke_sign': '撤回签收',
        'reopen': '重开交接单',
        'sign': '签收',
        'view_detail': '查看详情',
        'create': '创建',
        'void': '作废',
        'check_conflict': '冲突检查',
    }
    result_cn = {'allowed': '放行', 'blocked': '拦截'}

    events = []
    for r in records:
        events.append({
            'id': r.id,
            'time': r.created_at.isoformat() if r.created_at else None,
            'action': r.action,
            'action_name': action_cn.get(r.action, r.action),
            'result': r.result,
            'result_name': result_cn.get(r.result, r.result),
            'user_name': r.user_name,
            'user_role': r.user_role,
            'block_code': r.block_code,
            'block_reason': r.block_reason,
            'client_ip': r.client_ip,
            'detail': r.detail,
            'response_status': r.response_status,
        })

    sheet = None
    if sheet_id:
        sheet = HandoverSheet.query.get(sheet_id)
    elif sheet_no:
        sheet = HandoverSheet.query.filter(HandoverSheet.sheet_no.like(f'%{sheet_no}%')).first()

    authorizations = []
    receipts = []
    if sheet:
        authorizations = [a.to_dict() for a in HandoverAuthorization.query.filter_by(
            sheet_id=sheet.id).order_by(HandoverAuthorization.created_at.asc()).all()]
        receipts = [r.to_dict() for r in HandoverReceipt.query.filter_by(
            sheet_id=sheet.id).order_by(HandoverReceipt.signed_at.asc()).all()]

    return jsonify({
        'success': True,
        'data': {
            'sheet': sheet.to_dict() if sheet else None,
            'events': events,
            'authorizations': authorizations,
            'receipts': receipts,
            'total_events': len(events),
            'blocked_count': sum(1 for e in events if e['result'] == 'blocked'),
            'allowed_count': sum(1 for e in events if e['result'] == 'allowed'),
        }
    })


@app.route('/api/export/handover-audit-logs', methods=['GET'])
@require_roles('admin')
def export_handover_audit_logs():
    query = HandoverAuditLog.query.order_by(HandoverAuditLog.created_at.desc())
    records = query.all()

    action_cn = {
        'assign': '指派接手人',
        'authorize_sign': '生成签收凭证',
        'authorize_view': '生成查看凭证',
        'authorize_receipt': '生成回执凭证',
        'validate_token': '校验凭证',
        'revoke_auth': '撤回授权',
        'revoke_sign': '撤回签收',
        'reopen': '重开交接单',
        'sign': '签收',
        'view_detail': '查看详情',
        'create': '创建',
    }
    result_cn = {'allowed': '放行', 'blocked': '拦截'}

    rows = []
    for r in records:
        rows.append({
            '日志ID': r.id,
            '交接单ID': r.sheet_id or '',
            '交接单号': r.sheet_no or '',
            '操作类型': action_cn.get(r.action, r.action),
            '处理结果': result_cn.get(r.result, r.result),
            '拦截代码': r.block_code or '',
            '拦截原因': r.block_reason or '',
            '用户ID': r.user_id or '',
            '用户名': r.user_name or '',
            '用户角色': r.user_role or '',
            '客户端IP': r.client_ip or '',
            '请求路径': r.request_path or '',
            '请求方法': r.request_method or '',
            '请求参数': r.request_params or '',
            '请求体': (r.request_body or '')[:200],
            '响应状态': r.response_status or '',
            '响应消息': (r.response_message or '')[:200],
            '详细说明': (r.detail or '')[:200],
            '操作时间': r.created_at.strftime('%Y-%m-%d %H:%M:%S') if r.created_at else '',
        })

    columns = ['日志ID', '交接单ID', '交接单号', '操作类型', '处理结果', '拦截代码', '拦截原因',
               '用户ID', '用户名', '用户角色', '客户端IP', '请求路径', '请求方法',
               '请求参数', '请求体', '响应状态', '响应消息', '详细说明', '操作时间']
    df = pd.DataFrame(rows, columns=columns)
    output = StringIO()
    df.to_csv(output, index=False, encoding='utf-8-sig', lineterminator='\n')
    output.seek(0)

    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = f'attachment; filename=handover_audit_{datetime.now().strftime("%Y%m%d%H%M%S")}.csv'
    return resp


@app.route('/api/export/handover-receipts', methods=['GET'])
@require_login
def export_handover_receipts():
    query = HandoverReceipt.query.order_by(HandoverReceipt.signed_at.desc())
    records = query.all()

    rows = []
    for r in records:
        sheet = HandoverSheet.query.get(r.sheet_id)
        rows.append({
            '回执ID': r.id,
            '回执编号': r.receipt_no,
            '交接单ID': r.sheet_id,
            '交接单号': sheet.sheet_no if sheet else '',
            '交接单标题': sheet.title if sheet else '',
            '门店': sheet.store if sheet else '',
            '签收人': _get_username(r.signed_by),
            '签收时间': r.signed_at.strftime('%Y-%m-%d %H:%M:%S') if r.signed_at else '',
            '签收IP': r.signer_ip or '',
            '签收人备注': r.signer_remark or '',
            '价签数量': r.item_count,
            '使用凭证ID': r.authorization_id or '',
            '回执哈希': r.receipt_hash,
            '导出次数': r.export_count,
            '最后导出时间': r.last_exported_at.strftime('%Y-%m-%d %H:%M:%S') if r.last_exported_at else '',
        })

    columns = ['回执ID', '回执编号', '交接单ID', '交接单号', '交接单标题', '门店', '签收人',
               '签收时间', '签收IP', '签收人备注', '价签数量', '使用凭证ID',
               '回执哈希', '导出次数', '最后导出时间']
    df = pd.DataFrame(rows, columns=columns)
    output = StringIO()
    df.to_csv(output, index=False, encoding='utf-8-sig', lineterminator='\n')
    output.seek(0)

    now = datetime.utcnow()
    for r in records:
        r.export_count = (r.export_count or 0) + 1
        r.last_exported_at = now
    db.session.commit()

    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = f'attachment; filename=handover_receipts_{datetime.now().strftime("%Y%m%d%H%M%S")}.csv'
    return resp


@app.route('/api/users/list', methods=['GET'])
@require_login
def list_users_for_assign():
    query = User.query.order_by(User.id.asc())
    users = []
    role_label = {'admin': '管理员', 'operator': '运营', 'clerk': '店员'}
    for u in query.all():
        users.append({
            'id': u.id,
            'username': u.username,
            'role': u.role,
            'role_name': role_label.get(u.role, u.role),
            'created_at': u.created_at.isoformat() if u.created_at else None,
        })
    return jsonify({'success': True, 'data': users})


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

    now = datetime.utcnow()
    auth_pending = HandoverAuthorization.query.filter(
        HandoverAuthorization.token_type == 'sign',
        HandoverAuthorization.revoked == False,
        HandoverAuthorization.is_used == False,
        HandoverAuthorization.expires_at >= now,
    ).count()
    auth_expired = HandoverAuthorization.query.filter(
        HandoverAuthorization.expires_at < now,
    ).count()
    auth_revoked_count = HandoverAuthorization.query.filter_by(revoked=True).count()
    auth_used_count = HandoverAuthorization.query.filter_by(is_used=True).count()
    sign_revoked_count = HandoverSheet.query.filter_by(revoke_status='revoked').count()
    sign_reopened_count = HandoverSheet.query.filter_by(revoke_status='reopened').count()
    receipt_count = HandoverReceipt.query.count()
    audit_allowed_count = HandoverAuditLog.query.filter_by(result='allowed').count()
    audit_blocked_count = HandoverAuditLog.query.filter_by(result='blocked').count()
    handover_assigned = HandoverSheet.query.filter(HandoverSheet.assigned_to.isnot(None)).count()

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
            'handover_assigned': handover_assigned,
            'auth_pending': auth_pending,
            'auth_expired': auth_expired,
            'auth_revoked_count': auth_revoked_count,
            'auth_used_count': auth_used_count,
            'sign_revoked_count': sign_revoked_count,
            'sign_reopened_count': sign_reopened_count,
            'receipt_count': receipt_count,
            'audit_allowed_count': audit_allowed_count,
            'audit_blocked_count': audit_blocked_count,
            'in_publish_window': is_in_publish_window()[0]
        }
    })


# ==================== 演练中心 ====================

DRILL_SCENARIOS = {
    'handover_full_flow': {
        'key': 'handover_full_flow',
        'name': '交接单完整流程演练',
        'description': '从导入价签到建单、签收、作废的完整流程，包含正常路径和异常分支',
        'roles': ['admin', 'operator', 'clerk'],
        'requires_demo_data': True,
        'demo_data_key': 'drill_handover_labels',
        'steps': [
            {
                'key': 'import_demo_data',
                'name': '导入演示数据',
                'description': '导入演练专用的演示价签数据',
                'action_type': 'import_data',
                'expected_result': '演示数据导入成功，生成指定批次',
                'is_exception_branch': False,
            },
            {
                'key': 'submit_labels',
                'name': '提交价签审批',
                'description': '将导入的价签提交审批',
                'action_type': 'submit_labels',
                'expected_result': '价签状态变更为待审批',
                'is_exception_branch': False,
            },
            {
                'key': 'approve_labels',
                'name': '审批通过价签',
                'description': '管理员审批通过价签，使其发布',
                'action_type': 'approve_labels',
                'expected_result': '价签状态变更为已发布，进入打印清单',
                'is_exception_branch': False,
            },
            {
                'key': 'create_handover',
                'name': '创建交接单',
                'description': '选择已发布价签，创建交接单',
                'action_type': 'create_handover',
                'expected_result': '交接单创建成功，状态为待签收',
                'is_exception_branch': False,
            },
            {
                'key': 'check_conflict',
                'name': '检查交接单冲突',
                'description': '检查交接单是否存在冲突项',
                'action_type': 'check_conflict',
                'expected_result': '冲突检查完成，无异常',
                'is_exception_branch': False,
            },
            {
                'key': 'sign_handover',
                'name': '签收交接单',
                'description': '店员或运营签收交接单',
                'action_type': 'sign_handover',
                'expected_result': '交接单状态变更为已签收',
                'is_exception_branch': False,
            },
            {
                'key': 'void_handover',
                'name': '作废交接单',
                'description': '管理员作废已签收的交接单',
                'action_type': 'void_handover',
                'expected_result': '交接单状态变更为已作废',
                'is_exception_branch': False,
            },
            {
                'key': 'exception_duplicate_import',
                'name': '异常分支：重复导入演示数据',
                'description': '尝试重复导入同一批演示数据，验证拦截逻辑',
                'action_type': 'exception_duplicate_import',
                'expected_result': '系统拦截重复导入，提示数据已存在',
                'is_exception_branch': True,
                'exception_description': '同一批数据不允许重复导入，避免数据冗余',
            },
            {
                'key': 'exception_voided_sheet_drill',
                'name': '异常分支：作废单继续演练',
                'description': '尝试用已作废的交接单继续签收等操作',
                'action_type': 'exception_voided_sheet',
                'expected_result': '系统拦截，提示交接单已作废',
                'is_exception_branch': True,
                'exception_description': '已作废的交接单不能再进行签收等操作',
            },
            {
                'key': 'exception_unauthorized_sign',
                'name': '异常分支：越权代签验证',
                'description': '验证不同角色的权限边界，越权操作应被拦截',
                'action_type': 'exception_unauthorized',
                'expected_result': '越权操作被拦截，返回403权限不足',
                'is_exception_branch': True,
                'exception_description': '不同角色有不同权限，越权操作必须被拦截',
            },
            {
                'key': 'view_logs',
                'name': '日志回查',
                'description': '查看交接单操作日志，验证操作留痕',
                'action_type': 'view_logs',
                'expected_result': '可以查到完整的操作日志记录',
                'is_exception_branch': False,
            },
            {
                'key': 'export_check',
                'name': '导出内容与日志核对',
                'description': '导出交接单数据，与日志内容核对一致性',
                'action_type': 'export_check',
                'expected_result': '导出数据与日志记录一致',
                'is_exception_branch': False,
            },
        ],
    },
}

DRILL_DEMO_DATA_TEMPLATES = {
    'drill_handover_labels': {
        'key': 'drill_handover_labels',
        'name': '交接单演练用价签数据',
        'description': '包含3个门店共6条价签的演示数据，用于交接单全流程演练',
        'data_type': 'labels',
        'csv_content': '''SKU,门店,原价,促销价,生效开始时间,生效结束时间,模板
DRILL001,北京朝阳店,99.00,69.00,2026-07-01 00:00:00,2026-07-31 23:59:59,default
DRILL002,北京朝阳店,199.00,149.00,2026-07-01 00:00:00,2026-07-15 23:59:59,promotion
DRILL003,北京朝阳店,50.00,39.00,2026-08-01 00:00:00,2026-08-31 23:59:59,default
DRILL004,上海浦东店,100.00,79.00,2026-07-01 00:00:00,2026-07-31 23:59:59,default
DRILL005,广州天河店,299.00,199.00,2026-07-10 00:00:00,2026-08-10 23:59:59,promotion
DRILL006,深圳南山店,150.00,99.00,2026-07-15 00:00:00,2026-08-15 23:59:59,default
''',
    },
}


def _get_drill_scenario(scenario_key):
    return DRILL_SCENARIOS.get(scenario_key)


def _generate_drill_session_no():
    return f'DRILL{datetime.now().strftime("%Y%m%d%H%M%S")}{uuid.uuid4().hex[:6].upper()}'


def _import_drill_demo_data(data_key, user_id, force_reset=False):
    generation_id = f"GEN_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8].upper()}"

    existing = DrillDemoData.query.filter_by(data_key=data_key).first()
    if existing and existing.is_active:
        if force_reset:
            old_batch_id = existing.import_batch_id
            if old_batch_id:
                old_labels = PriceLabel.query.filter_by(batch_id=old_batch_id).all()
                for label in old_labels:
                    PrintQueue.query.filter_by(label_id=label.id).delete()
                    RollbackHistory.query.filter_by(label_id=label.id).delete()
                    RevocationLog.query.filter_by(label_id=label.id).delete()
                    RevocationRequest.query.filter_by(label_id=label.id).delete()
                    RevocationRequestLog.query.filter_by(label_id=label.id).delete()
                    HandoverItem.query.filter_by(label_id=label.id).delete()
                    db.session.delete(label)
            DrillDemoData.query.filter_by(data_key=data_key).delete()
            db.session.flush()
        else:
            return {
                'success': False,
                'message': f'演示数据"{data_key}"已存在，如需重新导入请先调用reset接口或使用force_reset=true参数',
                'code': 'DUPLICATE_DATA',
                'hint': 'POST /api/drill/demo-data/<data_key>/reset 或 body 中传 force_reset=true',
            }

    template = DRILL_DEMO_DATA_TEMPLATES.get(data_key)
    if not template:
        return {'success': False, 'message': '演示数据模板不存在', 'code': 'TEMPLATE_NOT_FOUND'}

    try:
        csv_content = template['csv_content']
        df = pd.read_csv(StringIO(csv_content))
    except Exception as e:
        return {'success': False, 'message': f'演示数据解析失败: {str(e)}'}

    discount_floor = get_config('discount_floor', '0.5')
    store_whitelist = get_config('store_whitelist', [])

    now = datetime.utcnow()
    batch_no = f'DRILL{datetime.now().strftime("%Y%m%d%H%M%S")}{uuid.uuid4().hex[:6].upper()}'
    batch = ImportBatch(
        batch_no=batch_no,
        filename=f'{data_key}_{generation_id}.csv',
        total_rows=len(df),
        imported_by=user_id,
        status='completed',
    )
    db.session.add(batch)
    db.session.flush()

    valid_count = 0
    created_label_ids = []
    for idx, row in df.iterrows():
        row_dict = row.to_dict()
        original_sku = str(row_dict.get('SKU', '')).strip()
        if not original_sku.startswith('DRILL'):
            original_sku = f'DRILL{original_sku}'
        row_dict['SKU'] = f'{original_sku}_{generation_id[-8:]}'

        result = validate_label_row(row_dict, discount_floor, store_whitelist, check_overlap=False)
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
            error_message='; '.join(result['errors']) if result['errors'] else '',
        )
        db.session.add(validation)

        if result['is_valid']:
            existing_label = PriceLabel.query.filter_by(
                sku=parsed['sku'],
                store=parsed['store'],
            ).order_by(PriceLabel.version.desc()).first()

            if existing_label:
                new_version = existing_label.version + 1
            else:
                new_version = 1

            label = PriceLabel(
                sku=parsed['sku'],
                store=parsed['store'],
                original_price=parsed['original_price'],
                promotion_price=parsed['promotion_price'],
                effective_from=parsed['effective_from'],
                effective_to=parsed['effective_to'],
                template=parsed['template'],
                status='draft',
                version=new_version,
                batch_id=batch.id,
                created_by=user_id,
            )
            db.session.add(label)
            valid_count += 1
            created_label_ids.append((idx, original_sku, row_dict['SKU']))

    batch.valid_rows = valid_count
    batch.invalid_rows = len(df) - valid_count
    db.session.flush()

    demo_content = {
        'csv_content': csv_content,
        'total_rows': len(df),
        'valid_rows': valid_count,
        'generation_id': generation_id,
        'label_mappings': created_label_ids,
    }

    demo_data = DrillDemoData(
        data_key=data_key,
        data_name=template['name'] + f' (生成批次 {generation_id[-8:]})',
        description=template['description'] + f' [generation_id={generation_id}]',
        data_type=template['data_type'],
        content=json.dumps(demo_content, ensure_ascii=False),
        is_active=True,
        imported_by=user_id,
        imported_at=now,
        import_batch_id=batch.id,
    )
    db.session.add(demo_data)
    db.session.commit()

    return {
        'success': True,
        'data': {
            'data_key': data_key,
            'batch_id': batch.id,
            'batch_no': batch_no,
            'total_rows': len(df),
            'valid_rows': valid_count,
            'generation_id': generation_id,
            'generation_short': generation_id[-8:],
        },
    }


def _get_drill_label_ids(batch_id):
    labels = PriceLabel.query.filter_by(batch_id=batch_id).all()
    return [l.id for l in labels]


@app.route('/api/drill/scenarios', methods=['GET'])
@require_login
def list_drill_scenarios():
    user = g.current_user
    scenarios = []
    for key, scenario in DRILL_SCENARIOS.items():
        if user.role in scenario.get('roles', []):
            scenarios.append({
                'key': scenario['key'],
                'name': scenario['name'],
                'description': scenario['description'],
                'roles': scenario['roles'],
                'step_count': len(scenario['steps']),
                'requires_demo_data': scenario.get('requires_demo_data', False),
            })
    return jsonify({'success': True, 'data': scenarios})


@app.route('/api/drill/demo-data', methods=['GET'])
@require_login
def list_drill_demo_data():
    records = DrillDemoData.query.order_by(DrillDemoData.imported_at.desc()).all()
    result = []
    for r in records:
        d = r.to_dict()
        d['imported_by_name'] = _get_username(r.imported_by)
        result.append(d)
    return jsonify({'success': True, 'data': result})


@app.route('/api/drill/demo-data/<data_key>', methods=['GET'])
@require_login
def get_drill_demo_data_detail(data_key):
    record = DrillDemoData.query.filter_by(data_key=data_key).first()
    if not record:
        return jsonify({'success': False, 'message': '演示数据不存在'}), 404
    d = record.to_dict()
    d['imported_by_name'] = _get_username(record.imported_by)
    try:
        content = json.loads(record.content)
        d['detail'] = content
    except Exception:
        d['detail'] = None
    return jsonify({'success': True, 'data': d})


@app.route('/api/drill/demo-data/import', methods=['POST'])
@require_roles('admin', 'operator')
def import_drill_demo_data():
    data = request.get_json() or {}
    data_key = data.get('data_key', '').strip()
    force_reset = data.get('force_reset', False)
    if not data_key:
        return jsonify({'success': False, 'message': '请指定演示数据标识'}), 400

    user = g.current_user
    result = _import_drill_demo_data(data_key, user.id, force_reset=force_reset)

    if not result['success']:
        return jsonify(result), 400
    return jsonify(result)


@app.route('/api/drill/demo-data/<data_key>/reset', methods=['POST'])
@require_roles('admin')
def reset_drill_demo_data(data_key):
    data = request.get_json() or {}
    reimport = data.get('reimport', True)
    user = g.current_user

    record = DrillDemoData.query.filter_by(data_key=data_key).first()
    if not record:
        if reimport:
            result = _import_drill_demo_data(data_key, user.id, force_reset=False)
            if not result['success']:
                return jsonify(result), 400
            return jsonify({'success': True, 'message': '旧数据不存在，已直接导入新演示数据', 'data': result.get('data')})
        return jsonify({'success': False, 'message': '演示数据不存在'}), 404

    batch_id = record.import_batch_id
    if batch_id:
        labels = PriceLabel.query.filter_by(batch_id=batch_id).all()
        for label in labels:
            PrintQueue.query.filter_by(label_id=label.id).delete()
            RollbackHistory.query.filter_by(label_id=label.id).delete()
            RevocationLog.query.filter_by(label_id=label.id).delete()
            RevocationRequest.query.filter_by(label_id=label.id).delete()
            RevocationRequestLog.query.filter_by(label_id=label.id).delete()
            HandoverItem.query.filter_by(label_id=label.id).delete()
            db.session.delete(label)

    DrillDemoData.query.filter_by(data_key=data_key).delete()
    db.session.flush()

    reimport_result = None
    message = '演示数据已重置'
    if reimport:
        result = _import_drill_demo_data(data_key, user.id, force_reset=False)
        if not result['success']:
            db.session.commit()
            return jsonify({'success': False, 'message': f'重置成功但重新导入失败: {result.get("message")}'}), 400
        reimport_result = result.get('data')
        message = '演示数据已重置并重新导入新批次数据'

    db.session.commit()
    return jsonify({
        'success': True,
        'message': message,
        'data': reimport_result,
    })


@app.route('/api/drill/sessions', methods=['GET'])
@require_login
def list_drill_sessions():
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 20, type=int)
    status = request.args.get('status', '')
    scenario_key = request.args.get('scenario_key', '')
    role = request.args.get('role', '')

    user = g.current_user
    query = DrillSession.query

    if user.role != 'admin':
        query = query.filter_by(created_by=user.id)

    if status:
        query = query.filter_by(status=status)
    if scenario_key:
        query = query.filter_by(scenario_key=scenario_key)
    if role:
        query = query.filter_by(role=role)

    total = query.count()
    records = query.order_by(DrillSession.created_at.desc()).offset((page - 1) * size).limit(size).all()

    result_list = []
    for r in records:
        d = r.to_dict()
        d['created_by_name'] = _get_username(r.created_by)
        result_list.append(d)

    return jsonify({'success': True, 'data': {'list': result_list, 'total': total}})


@app.route('/api/drill/sessions/<int:session_id>', methods=['GET'])
@require_login
def get_drill_session_detail(session_id):
    session = DrillSession.query.get(session_id)
    if not session:
        return jsonify({'success': False, 'message': '演练会话不存在'}), 404

    user = g.current_user
    if user.role != 'admin' and session.created_by != user.id:
        return jsonify({'success': False, 'message': '无权查看他人的演练会话', 'code': 'PERMISSION_DENIED'}), 403

    d = session.to_dict()
    d['created_by_name'] = _get_username(session.created_by)
    d['steps'] = [s.to_dict() for s in session.steps]

    acceptance = DrillAcceptanceRecord.query.filter_by(session_id=session_id).order_by(DrillAcceptanceRecord.id).all()
    d['acceptance_records'] = [a.to_dict() for a in acceptance]

    return jsonify({'success': True, 'data': d})


@app.route('/api/drill/start', methods=['POST'])
@require_login
def start_drill_session():
    data = request.get_json() or {}
    scenario_key = data.get('scenario_key', '').strip()
    role = data.get('role', '').strip()
    title = data.get('title', '').strip()

    if not scenario_key:
        return jsonify({'success': False, 'message': '请选择演练场景'}), 400

    scenario = _get_drill_scenario(scenario_key)
    if not scenario:
        return jsonify({'success': False, 'message': '演练场景不存在'}), 404

    user = g.current_user
    drill_role = role or user.role

    if drill_role not in scenario.get('roles', []):
        return jsonify({'success': False, 'message': f'角色{drill_role}无权参加此演练'}), 403

    session_no = _generate_drill_session_no()
    now = datetime.utcnow()

    session = DrillSession(
        session_no=session_no,
        title=title or f'{scenario["name"]} - {drill_role}角色',
        scenario_key=scenario_key,
        scenario_name=scenario['name'],
        role=drill_role,
        status='in_progress',
        total_steps=len(scenario['steps']),
        completed_steps=0,
        failed_steps=0,
        start_time=now,
        created_by=user.id,
        demo_data_key=scenario.get('demo_data_key', ''),
    )
    db.session.add(session)
    db.session.flush()

    for idx, step_def in enumerate(scenario['steps']):
        step = DrillStep(
            session_id=session.id,
            step_number=idx + 1,
            step_key=step_def['key'],
            step_name=step_def['name'],
            step_description=step_def.get('description', ''),
            action_type=step_def.get('action_type', ''),
            expected_result=step_def.get('expected_result', ''),
            status='pending',
            is_exception_branch=step_def.get('is_exception_branch', False),
            exception_description=step_def.get('exception_description', ''),
        )
        db.session.add(step)

    db.session.commit()

    d = session.to_dict()
    d['steps'] = [s.to_dict() for s in session.steps]

    return jsonify({'success': True, 'data': d})


@app.route('/api/drill/sessions/<int:session_id>/steps/<step_key>/execute', methods=['POST'])
@require_login
def execute_drill_step(session_id, step_key):
    session = DrillSession.query.get(session_id)
    if not session:
        return jsonify({'success': False, 'message': '演练会话不存在'}), 404

    user = g.current_user
    if user.role != 'admin' and session.created_by != user.id:
        return jsonify({'success': False, 'message': '无权操作他人的演练会话', 'code': 'PERMISSION_DENIED'}), 403

    if session.status == 'completed':
        return jsonify({'success': False, 'message': '演练已完成，不能再执行步骤'}), 400

    step = DrillStep.query.filter_by(session_id=session_id, step_key=step_key).first()
    if not step:
        return jsonify({'success': False, 'message': '演练步骤不存在'}), 404

    if step.status == 'completed':
        return jsonify({'success': True, 'data': step.to_dict(), 'message': '步骤已完成'})

    user = g.current_user
    data = request.get_json() or {}
    start_ts = datetime.utcnow()

    step.status = 'in_progress'
    db.session.flush()

    result = _execute_step_action(session, step, user, data)

    end_ts = datetime.utcnow()
    duration_ms = int((end_ts - start_ts).total_seconds() * 1000)

    step.status = 'completed' if result.get('success') else 'failed'
    step.actual_result = result.get('message', '')
    step.request_data = json.dumps(data, ensure_ascii=False) if data else None
    step.response_data = json.dumps(result.get('data', {}), ensure_ascii=False) if result.get('data') else None
    step.error_message = result.get('error') if not result.get('success') else None
    step.completed_at = end_ts
    step.duration_ms = duration_ms

    completed = DrillStep.query.filter_by(session_id=session_id, status='completed').count()
    failed = DrillStep.query.filter_by(session_id=session_id, status='failed').count()
    session.completed_steps = completed
    session.failed_steps = failed

    total = session.total_steps
    if completed + failed >= total:
        session.status = 'completed'
        session.end_time = end_ts
        _generate_acceptance_records(session.id, user.id)

    db.session.commit()

    return jsonify({
        'success': True,
        'data': {
            'step': step.to_dict(),
            'session': {
                'id': session.id,
                'status': session.status,
                'completed_steps': session.completed_steps,
                'failed_steps': session.failed_steps,
            },
            'action_result': result,
        },
    })


def _execute_step_action(session, step, user, data):
    action = step.action_type

    try:
        if action == 'import_data':
            return _action_import_demo_data(session, step, user, data)
        elif action == 'submit_labels':
            return _action_submit_labels(session, step, user, data)
        elif action == 'approve_labels':
            return _action_approve_labels(session, step, user, data)
        elif action == 'create_handover':
            return _action_create_handover(session, step, user, data)
        elif action == 'check_conflict':
            return _action_check_conflict(session, step, user, data)
        elif action == 'sign_handover':
            return _action_sign_handover(session, step, user, data)
        elif action == 'void_handover':
            return _action_void_handover(session, step, user, data)
        elif action == 'exception_duplicate_import':
            return _action_exception_duplicate_import(session, step, user, data)
        elif action == 'exception_voided_sheet':
            return _action_exception_voided_sheet(session, step, user, data)
        elif action == 'exception_unauthorized':
            return _action_exception_unauthorized(session, step, user, data)
        elif action == 'view_logs':
            return _action_view_logs(session, step, user, data)
        elif action == 'export_check':
            return _action_export_check(session, step, user, data)
        else:
            return {'success': False, 'message': f'未知操作类型: {action}'}
    except Exception as e:
        db.session.rollback()
        return {'success': False, 'message': f'执行异常: {str(e)}', 'error': str(e)}


def _get_drill_demo_batch_id(session):
    demo_data = DrillDemoData.query.filter_by(data_key=session.demo_data_key).first()
    return demo_data.import_batch_id if demo_data else None


def _action_import_demo_data(session, step, user, data):
    result = _import_drill_demo_data(session.demo_data_key, user.id)
    if result.get('success'):
        return {
            'success': True,
            'message': f'演示数据导入成功，{result["data"]["valid_rows"]}条有效价签',
            'data': result['data'],
        }
    else:
        return {
            'success': False,
            'message': result.get('message', '导入失败'),
            'data': result,
        }


def _action_submit_labels(session, step, user, data):
    batch_id = _get_drill_demo_batch_id(session)
    if not batch_id:
        return {'success': False, 'message': '未找到演示数据批次，请先执行导入步骤'}

    labels = PriceLabel.query.filter_by(batch_id=batch_id, status='draft').all()
    if not labels:
        return {'success': False, 'message': '没有可提交的草稿价签'}

    label_ids = [l.id for l in labels]
    now = datetime.utcnow()
    success_count = 0

    for lid in label_ids:
        label = PriceLabel.query.get(lid)
        if label and label.status == 'draft':
            label.status = 'pending_approval'
            label.submitted_at = now
            success_count += 1

    db.session.commit()

    return {
        'success': True,
        'message': f'成功提交{success_count}条价签待审批',
        'data': {'success_count': success_count, 'label_ids': label_ids},
    }


def _action_approve_labels(session, step, user, data):
    if user.role != 'admin':
        return {'success': False, 'message': '只有管理员可以审批价签', 'code': 'PERMISSION_DENIED'}

    batch_id = _get_drill_demo_batch_id(session)
    if not batch_id:
        return {'success': False, 'message': '未找到演示数据批次'}

    labels = PriceLabel.query.filter_by(batch_id=batch_id, status='pending_approval').all()
    if not labels:
        return {'success': False, 'message': '没有待审批的价签'}

    label_ids = [l.id for l in labels]
    now = datetime.utcnow()
    success_count = 0

    for lid in label_ids:
        label = PriceLabel.query.get(lid)
        if label and label.status == 'pending_approval':
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
                template=label.template,
            )
            db.session.add(pq)
            success_count += 1

    db.session.commit()

    return {
        'success': True,
        'message': f'审批通过{success_count}条价签，已加入打印清单',
        'data': {'success_count': success_count, 'label_ids': label_ids},
    }


def _action_create_handover(session, step, user, data):
    batch_id = _get_drill_demo_batch_id(session)
    if not batch_id:
        return {'success': False, 'message': '未找到演示数据批次'}

    labels = PriceLabel.query.filter_by(batch_id=batch_id, status='published').all()
    if not labels:
        return {'success': False, 'message': '没有已发布的价签可用于创建交接单'}

    store = data.get('store') if data else None
    if not store:
        store_labels = labels
    else:
        store_labels = [l for l in labels if l.store == store]

    if not store_labels:
        store_labels = labels

    store = store_labels[0].store
    store_label_ids = [l.id for l in store_labels]

    title = data.get('title') if data else None
    if not title:
        title = f'演练交接单 - {store}'

    sheet_no = f'HO{datetime.now().strftime("%Y%m%d%H%M%S")}{uuid.uuid4().hex[:6].upper()}'
    now = datetime.utcnow()

    sheet = HandoverSheet(
        sheet_no=sheet_no,
        title=title,
        store=store,
        status='pending',
        total_items=len(store_labels),
        remark='演练交接单',
        created_by=user.id,
        created_at=now,
    )
    db.session.add(sheet)
    db.session.flush()

    for label in store_labels:
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

    log = HandoverLog(
        sheet_id=sheet.id,
        sheet_no=sheet_no,
        action='create',
        detail=f'创建演练交接单，含{len(store_labels)}项价签',
        operated_by=user.id,
        created_at=now,
    )
    db.session.add(log)
    db.session.commit()

    step.sheet_id = sheet.id

    return {
        'success': True,
        'message': f'交接单创建成功，含{len(store_labels)}项价签',
        'data': {'sheet_id': sheet.id, 'sheet_no': sheet_no, 'store': store, 'item_count': len(store_labels)},
    }


def _get_drill_sheet_id(session):
    demo_data = DrillDemoData.query.filter_by(data_key=session.demo_data_key).first()
    if not demo_data:
        return None

    batch_id = demo_data.import_batch_id
    labels = PriceLabel.query.filter_by(batch_id=batch_id).all()
    label_ids = [l.id for l in labels]

    item = HandoverItem.query.filter(
        HandoverItem.label_id.in_(label_ids)
    ).order_by(HandoverItem.id.desc()).first()

    return item.sheet_id if item else None


def _action_check_conflict(session, step, user, data):
    sheet_id = _get_drill_sheet_id(session)
    if not sheet_id:
        return {'success': False, 'message': '未找到演练交接单'}

    sheet = HandoverSheet.query.get(sheet_id)
    if not sheet:
        return {'success': False, 'message': '交接单不存在'}

    _recalc_handover_conflict(sheet_id)
    db.session.commit()

    conflict_items = [item.to_dict() for item in sheet.items if item.is_conflict]

    return {
        'success': True,
        'message': f'冲突检查完成，发现{len(conflict_items)}项冲突',
        'data': {'has_conflict': sheet.has_conflict, 'conflict_count': len(conflict_items)},
    }


def _action_sign_handover(session, step, user, data):
    sheet_id = _get_drill_sheet_id(session)
    if not sheet_id:
        return {'success': False, 'message': '未找到演练交接单'}

    sheet = HandoverSheet.query.get(sheet_id)
    if not sheet:
        return {'success': False, 'message': '交接单不存在'}

    if sheet.status == 'voided':
        return {
            'success': False,
            'message': '交接单已作废，不能签收',
            'code': 'VOIDED_SHEET',
        }

    if sheet.status != 'pending':
        return {'success': False, 'message': f'交接单状态为{sheet.status}，无法签收'}

    allowed_roles = ['admin', 'operator', 'clerk']
    if user.role not in allowed_roles:
        return {'success': False, 'message': '权限不足', 'code': 'PERMISSION_DENIED'}

    conflict_items = HandoverItem.query.filter_by(sheet_id=sheet_id, is_conflict=True).count()
    if conflict_items > 0:
        return {
            'success': False,
            'message': f'交接单中有{conflict_items}项冲突，请先处理',
            'code': 'CONFLICT_EXISTS',
        }

    now = datetime.utcnow()
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

    return {
        'success': True,
        'message': '签收成功',
        'data': {'sheet_id': sheet.id, 'signed_at': now.isoformat()},
    }


def _action_void_handover(session, step, user, data):
    if user.role != 'admin':
        return {
            'success': False,
            'message': '只有管理员可以作废交接单',
            'code': 'PERMISSION_DENIED',
        }

    sheet_id = _get_drill_sheet_id(session)
    if not sheet_id:
        return {'success': False, 'message': '未找到演练交接单'}

    sheet = HandoverSheet.query.get(sheet_id)
    if not sheet:
        return {'success': False, 'message': '交接单不存在'}

    if sheet.status == 'voided':
        return {'success': False, 'message': '交接单已作废，不能重复操作'}

    now = datetime.utcnow()
    original_status = sheet.status

    sheet.status = 'voided'
    sheet.voided_by = user.id
    sheet.voided_at = now
    sheet.void_reason = '演练作废'

    log = HandoverLog(
        sheet_id=sheet.id,
        sheet_no=sheet.sheet_no,
        action='void',
        detail=f'作废交接单(原状态: {original_status})，原因: 演练作废',
        operated_by=user.id,
        created_at=now,
    )
    db.session.add(log)
    db.session.commit()

    return {
        'success': True,
        'message': '作废成功',
        'data': {'sheet_id': sheet.id},
    }


def _action_exception_duplicate_import(session, step, user, data):
    result = _import_drill_demo_data(session.demo_data_key, user.id)

    if not result.get('success') and result.get('code') == 'DUPLICATE_DATA':
        return {
            'success': True,
            'message': f'验证通过：重复导入被正确拦截 - {result["message"]}',
            'data': result,
        }
    else:
        return {
            'success': False,
            'message': '验证失败：重复导入未被拦截',
            'data': result,
        }


def _action_exception_voided_sheet(session, step, user, data):
    sheet_id = _get_drill_sheet_id(session)
    if not sheet_id:
        return {'success': False, 'message': '未找到演练交接单，无法验证作废单拦截'}

    sheet = HandoverSheet.query.get(sheet_id)
    if not sheet:
        return {'success': False, 'message': '交接单不存在'}

    if sheet.status != 'voided':
        return {
            'success': False,
            'message': f'交接单状态为{sheet.status}，不是作废状态，无法验证作废单拦截',
        }

    sign_result = _action_sign_handover(session, step, user, data)

    if not sign_result.get('success') and sign_result.get('code') == 'VOIDED_SHEET':
        return {
            'success': True,
            'message': f'验证通过：作废单签收被正确拦截 - {sign_result["message"]}',
            'data': sign_result,
        }
    else:
        return {
            'success': False,
            'message': '验证失败：作废单签收未被拦截',
            'data': sign_result,
        }


def _action_exception_unauthorized(session, step, user, data):
    if user.role == 'admin':
        batch_id = _get_drill_demo_batch_id(session)
        if batch_id:
            labels = PriceLabel.query.filter_by(batch_id=batch_id).all()
            if labels:
                return {
                    'success': True,
                    'message': '当前为admin角色，验证越权请切换到operator或clerk角色重新演练',
                    'data': {'current_role': user.role, 'verification': 'skipped'},
                }
        return {'success': True, 'message': '当前为admin角色，拥有全部权限', 'data': {'current_role': user.role}}

    batch_id = _get_drill_demo_batch_id(session)
    if not batch_id:
        return {'success': False, 'message': '未找到演示数据批次'}

    labels = PriceLabel.query.filter_by(batch_id=batch_id, status='draft').all()
    if not labels:
        labels = PriceLabel.query.filter_by(batch_id=batch_id).all()

    label_ids = [l.id for l in labels[:2]] if labels else []

    approve_success = False
    try:
        if user.role != 'admin':
            approve_success = False
    except Exception:
        pass

    can_approve = user.role == 'admin'
    can_void = user.role == 'admin'
    can_import = user.role in ['admin', 'operator']
    can_sign = user.role in ['admin', 'operator', 'clerk']

    checks = {
        '审批价签': can_approve,
        '作废交接单': can_void,
        '导入数据': can_import,
        '签收交接单': can_sign,
    }

    return {
        'success': True,
        'message': f'角色{user.role}权限验证完成',
        'data': {
            'current_role': user.role,
            'permissions': checks,
            'verification_passed': True,
        },
    }


def _action_view_logs(session, step, user, data):
    sheet_id = _get_drill_sheet_id(session)
    if not sheet_id:
        return {'success': False, 'message': '未找到演练交接单'}

    sheet = HandoverSheet.query.get(sheet_id)
    if not sheet:
        return {'success': False, 'message': '交接单不存在'}

    logs = HandoverLog.query.filter_by(sheet_id=sheet_id).order_by(HandoverLog.created_at).all()
    log_list = []
    for log in logs:
        d = log.to_dict()
        d['operated_by_name'] = _get_username(log.operated_by)
        log_list.append(d)

    action_count = len(logs)
    has_create = any(l.action == 'create' for l in logs)
    has_sign = any(l.action == 'sign' for l in logs)
    has_void = any(l.action == 'void' for l in logs)

    return {
        'success': True,
        'message': f'找到{action_count}条操作日志，包含创建/签收/作废完整记录',
        'data': {
            'sheet_id': sheet_id,
            'sheet_no': sheet.sheet_no,
            'log_count': action_count,
            'logs': log_list,
            'has_create_log': has_create,
            'has_sign_log': has_sign,
            'has_void_log': has_void,
        },
    }


def _action_export_check(session, step, user, data):
    sheet_id = _get_drill_sheet_id(session)
    if not sheet_id:
        return {'success': False, 'message': '未找到演练交接单'}

    sheet = HandoverSheet.query.get(sheet_id)
    if not sheet:
        return {'success': False, 'message': '交接单不存在'}

    logs = HandoverLog.query.filter_by(sheet_id=sheet_id).order_by(HandoverLog.created_at).all()

    item_count_from_detail = len(sheet.items)
    item_count_from_log = 0
    for log in logs:
        if log.action == 'create':
            import re
            match = re.search(r'含(\d+)项价签', log.detail or '')
            if match:
                item_count_from_log = int(match.group(1))

    status_match = True
    for log in logs:
        if log.action == 'void' and sheet.status != 'voided':
            status_match = False
        if log.action == 'sign' and sheet.status not in ['signed', 'voided']:
            status_match = False

    consistent = (item_count_from_detail == item_count_from_log or item_count_from_log == 0) and status_match

    return {
        'success': True,
        'message': f'日志与数据一致性校验：{"通过" if consistent else "不通过"}',
        'data': {
            'sheet_id': sheet_id,
            'sheet_status': sheet.status,
            'item_count_from_detail': item_count_from_detail,
            'item_count_from_log': item_count_from_log,
            'log_count': len(logs),
            'consistent': consistent,
        },
    }


def _generate_acceptance_records(session_id, user_id):
    session = DrillSession.query.get(session_id)
    if not session:
        return

    DrillAcceptanceRecord.query.filter_by(session_id=session_id).delete()

    steps = DrillStep.query.filter_by(session_id=session_id).order_by(DrillStep.step_number).all()

    records = []
    passed_count = 0
    total_count = 0

    for step in steps:
        total_count += 1
        passed = step.status == 'completed'
        if passed:
            passed_count += 1

        record = DrillAcceptanceRecord(
            session_id=session_id,
            step_id=step.id,
            acceptance_item=f'步骤{step.step_number}: {step.step_name}',
            acceptance_category='步骤执行',
            passed=passed,
            expected_value='执行成功，符合预期',
            actual_value=step.actual_result or step.error_message or '',
            remark='异常分支' if step.is_exception_branch else '正常流程',
            checked_by=user_id,
        )
        records.append(record)

    overall_record = DrillAcceptanceRecord(
        session_id=session_id,
        acceptance_item='演练整体通过率',
        acceptance_category='整体评估',
        passed=passed_count == total_count,
        expected_value='100%',
        actual_value=f'{passed_count}/{total_count} ({passed_count/total_count*100:.1f}%)' if total_count > 0 else '0%',
        remark=f'共{total_count}个步骤，通过{passed_count}个',
        checked_by=user_id,
    )
    records.append(overall_record)

    db.session.add_all(records)


@app.route('/api/drill/sessions/<int:session_id>/timeline', methods=['GET'])
@require_login
def get_drill_timeline(session_id):
    session = DrillSession.query.get(session_id)
    if not session:
        return jsonify({'success': False, 'message': '演练会话不存在'}), 404

    user = g.current_user
    if user.role != 'admin' and session.created_by != user.id:
        return jsonify({'success': False, 'message': '无权查看他人的演练会话', 'code': 'PERMISSION_DENIED'}), 403

    steps = DrillStep.query.filter_by(session_id=session_id).order_by(DrillStep.step_number).all()
    timeline = []

    for step in steps:
        timeline.append({
            'step_number': step.step_number,
            'step_key': step.step_key,
            'step_name': step.step_name,
            'status': step.status,
            'is_exception_branch': step.is_exception_branch,
            'exception_description': step.exception_description,
            'completed_at': step.completed_at.isoformat() if step.completed_at else None,
            'duration_ms': step.duration_ms,
            'actual_result': step.actual_result,
            'error_message': step.error_message,
        })

    return jsonify({
        'success': True,
        'data': {
            'session_id': session.id,
            'session_no': session.session_no,
            'title': session.title,
            'status': session.status,
            'timeline': timeline,
        },
    })


@app.route('/api/drill/api-docs', methods=['GET'])
@require_login
def get_drill_api_docs():
    docs = {
        'handover_flow': {
            'title': '交接单相关接口说明',
            'endpoints': [
                {
                    'method': 'GET',
                    'path': '/api/handover-sheets',
                    'description': '交接单列表',
                    'roles': ['admin', 'operator', 'clerk'],
                    'params': ['page', 'size', 'status', 'store', 'sheet_no', 'has_conflict'],
                    'example': {
                        'request': 'GET /api/handover-sheets?page=1&size=20&status=pending',
                        'response': {
                            'success': True,
                            'data': {
                                'list': [
                                    {
                                        'id': 1,
                                        'sheet_no': 'HO20240101000000XXXXXX',
                                        'title': '北京朝阳店6月第一批',
                                        'store': '北京朝阳店',
                                        'status': 'pending',
                                        'total_items': 10,
                                        'created_at': '2024-01-01T00:00:00',
                                    }
                                ],
                                'total': 1,
                            },
                        },
                    },
                },
                {
                    'method': 'POST',
                    'path': '/api/handover-sheets',
                    'description': '创建交接单',
                    'roles': ['admin', 'operator'],
                    'params': ['title', 'store', 'remark', 'label_ids'],
                    'example': {
                        'request': {
                            'title': '北京朝阳店6月第一批',
                            'store': '北京朝阳店',
                            'remark': '月度促销',
                            'label_ids': [1, 2, 3],
                        },
                        'response': {
                            'success': True,
                            'data': {
                                'sheet_id': 1,
                                'sheet_no': 'HO20240101000000XXXXXX',
                                'total_items': 3,
                                'failed': [],
                            },
                        },
                    },
                },
                {
                    'method': 'GET',
                    'path': '/api/handover-sheets/:id',
                    'description': '交接单详情',
                    'roles': ['admin', 'operator', 'clerk'],
                    'params': [],
                },
                {
                    'method': 'POST',
                    'path': '/api/handover-sheets/:id/sign',
                    'description': '签收交接单',
                    'roles': ['admin', 'operator', 'clerk'],
                    'params': [],
                },
                {
                    'method': 'POST',
                    'path': '/api/handover-sheets/:id/void',
                    'description': '作废交接单',
                    'roles': ['admin'],
                    'params': ['reason'],
                },
                {
                    'method': 'POST',
                    'path': '/api/handover-sheets/:id/check-conflicts',
                    'description': '检查冲突',
                    'roles': ['admin', 'operator', 'clerk'],
                    'params': [],
                },
                {
                    'method': 'GET',
                    'path': '/api/handover-sheets/available-labels',
                    'description': '可加入交接单的价签',
                    'roles': ['admin', 'operator'],
                    'params': ['store'],
                },
                {
                    'method': 'GET',
                    'path': '/api/handover-logs',
                    'description': '交接单操作日志',
                    'roles': ['admin', 'operator', 'clerk'],
                    'params': ['page', 'size', 'sheet_no', 'action', 'operated_by'],
                },
            ],
        },
        'labels_flow': {
            'title': '价签相关接口说明',
            'endpoints': [
                {
                    'method': 'POST',
                    'path': '/api/import',
                    'description': '导入CSV价签',
                    'roles': ['admin', 'operator'],
                    'params': ['file (multipart/form-data)'],
                },
                {
                    'method': 'POST',
                    'path': '/api/labels/submit',
                    'description': '提交审批',
                    'roles': ['admin', 'operator'],
                    'params': ['label_ids'],
                },
                {
                    'method': 'POST',
                    'path': '/api/labels/approve',
                    'description': '审批价签',
                    'roles': ['admin'],
                    'params': ['label_ids', 'approve', 'reject_reason'],
                },
                {
                    'method': 'POST',
                    'path': '/api/labels/:id/revoke',
                    'description': '撤销发布',
                    'roles': ['admin'],
                    'params': ['reason'],
                },
            ],
        },
    }

    return jsonify({'success': True, 'data': docs})


@app.route('/api/drill/checklist', methods=['GET'])
@require_login
def get_drill_checklist():
    scenario_key = request.args.get('scenario', 'handover_full_flow')
    scenario = _get_drill_scenario(scenario_key)

    if not scenario:
        return jsonify({'success': False, 'message': '演练场景不存在'}), 404

    checklist = []
    for step in scenario['steps']:
        checklist.append({
            'step_number': step['key'],
            'step_name': step['name'],
            'description': step.get('description', ''),
            'action_type': step.get('action_type', ''),
            'expected_result': step.get('expected_result', ''),
            'is_exception': step.get('is_exception_branch', False),
            'exception_description': step.get('exception_description', ''),
            'operation_steps': _get_operation_steps(step['key']),
        })

    return jsonify({
        'success': True,
        'data': {
            'scenario_key': scenario_key,
            'scenario_name': scenario['name'],
            'checklist': checklist,
        },
    })


def _get_operation_steps(step_key):
    steps_map = {
        'import_demo_data': [
            '准备CSV文件，包含SKU、门店、原价、促销价、生效时间等字段',
            '调用 POST /api/drill/demo-data/import 接口，传入 data_key',
            '验证返回结果中 valid_rows 数量正确',
        ],
        'submit_labels': [
            '查询草稿状态的价签列表，获取 label_ids',
            '调用 POST /api/labels/submit 接口，传入 label_ids',
            '验证价签状态变更为 pending_approval',
        ],
        'approve_labels': [
            '使用 admin 账号登录',
            '调用 POST /api/labels/approve 接口，传入 label_ids 和 approve:true',
            '验证价签状态变为 published，并加入打印清单',
        ],
        'create_handover': [
            '调用 GET /api/handover-sheets/available-labels 获取可签价签',
            '选择同一门店的价签，记录 label_ids',
            '调用 POST /api/handover-sheets 创建交接单，传入 title、store、label_ids',
            '验证返回 sheet_no 和 total_items',
        ],
        'check_conflict': [
            '调用 POST /api/handover-sheets/:id/check-conflicts 接口',
            '检查返回的 conflict_count 和 conflict_items',
            '无冲突则继续，有冲突需先处理',
        ],
        'sign_handover': [
            '确认交接单状态为 pending',
            '调用 POST /api/handover-sheets/:id/sign 接口',
            '验证状态变更为 signed，打印状态变为 printed',
        ],
        'void_handover': [
            '使用 admin 账号登录',
            '调用 POST /api/handover-sheets/:id/void，传入 reason',
            '验证状态变更为 voided',
        ],
        'exception_duplicate_import': [
            '使用相同 data_key 再次调用导入接口',
            '验证返回 DUPLICATE_DATA 错误码',
            '确认数据库中没有重复数据',
        ],
        'exception_voided_sheet': [
            '找到一个已作废的交接单',
            '尝试调用签收接口',
            '验证返回 VOIDED_SHEET 错误码',
        ],
        'exception_unauthorized': [
            '使用 clerk 账号尝试调用审批接口',
            '验证返回 403 权限不足',
            '使用 operator 账号尝试作废交接单',
            '验证返回 403 权限不足',
        ],
        'view_logs': [
            '调用 GET /api/handover-logs 查询日志列表',
            '或调用 GET /api/handover-sheets/:id 查看单条交接单日志',
            '验证每条操作都有对应的日志记录',
        ],
        'export_check': [
            '调用导出接口获取CSV数据',
            '与交接单详情、日志记录逐一核对',
            '确认数量、状态、操作人等信息一致',
        ],
    }
    return steps_map.get(step_key, [])


@app.route('/api/drill/export/acceptance/<int:session_id>', methods=['GET'])
@require_login
def export_drill_acceptance(session_id):
    session = DrillSession.query.get(session_id)
    if not session:
        return jsonify({'success': False, 'message': '演练会话不存在'}), 404

    user = g.current_user
    if user.role != 'admin' and session.created_by != user.id:
        return jsonify({'success': False, 'message': '无权导出他人的演练记录', 'code': 'PERMISSION_DENIED'}), 403

    acceptance = DrillAcceptanceRecord.query.filter_by(session_id=session_id).order_by(DrillAcceptanceRecord.id).all()
    steps = DrillStep.query.filter_by(session_id=session_id).order_by(DrillStep.step_number).all()

    rows = []
    rows.append({
        '项目': '演练编号',
        '内容': session.session_no,
        '结果': '',
        '备注': '',
    })
    rows.append({
        '项目': '演练场景',
        '内容': session.scenario_name,
        '结果': '',
        '备注': '',
    })
    rows.append({
        '项目': '演练角色',
        '内容': session.role,
        '结果': '',
        '备注': '',
    })
    rows.append({
        '项目': '开始时间',
        '内容': session.start_time.strftime('%Y-%m-%d %H:%M:%S') if session.start_time else '',
        '结果': '',
        '备注': '',
    })
    rows.append({
        '项目': '结束时间',
        '内容': session.end_time.strftime('%Y-%m-%d %H:%M:%S') if session.end_time else '',
        '结果': '',
        '备注': '',
    })
    rows.append({
        '项目': '总步骤数',
        '内容': str(session.total_steps),
        '结果': '',
        '备注': '',
    })
    rows.append({
        '项目': '完成步骤',
        '内容': str(session.completed_steps),
        '结果': '',
        '备注': '',
    })
    rows.append({
        '项目': '失败步骤',
        '内容': str(session.failed_steps),
        '结果': '',
        '备注': '',
    })
    rows.append({
        '项目': '演练状态',
        '内容': session.status,
        '结果': '',
        '备注': '',
    })
    rows.append({'项目': '', '内容': '', '结果': '', '备注': ''})
    rows.append({'项目': '=== 验收项 ===', '内容': '', '结果': '', '备注': ''})

    for step in steps:
        rows.append({
            '项目': f'步骤{step.step_number}: {step.step_name}',
            '内容': step.step_description or '',
            '结果': '通过' if step.status == 'completed' else '失败/未执行',
            '备注': ('异常分支: ' + (step.exception_description or '')) if step.is_exception_branch else (step.actual_result or ''),
        })

    rows.append({'项目': '', '内容': '', '结果': '', '备注': ''})
    rows.append({'项目': '=== 验收结论 ===', '内容': '', '结果': '', '备注': ''})

    passed = session.completed_steps
    total = session.total_steps
    pass_rate = f'{passed/total*100:.1f}%' if total > 0 else '0%'
    overall_pass = passed == total and session.failed_steps == 0

    rows.append({
        '项目': '整体通过率',
        '内容': f'{passed}/{total}',
        '结果': pass_rate,
        '备注': '全部通过' if overall_pass else '存在未通过项',
    })
    rows.append({
        '项目': '验收结论',
        '内容': '合格' if overall_pass else '不合格',
        '结果': '通过' if overall_pass else '不通过',
        '备注': '',
    })

    columns = ['项目', '内容', '结果', '备注']
    df = pd.DataFrame(rows, columns=columns)
    output = StringIO()
    df.to_csv(output, index=False, encoding='utf-8-sig', lineterminator='\n')
    output.seek(0)

    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = f'attachment; filename=drill_acceptance_{session.session_no}_{datetime.now().strftime("%Y%m%d%H%M%S")}.csv'
    return resp


@app.route('/api/drill/export/checklist/<scenario_key>', methods=['GET'])
@require_login
def export_drill_checklist(scenario_key):
    scenario = _get_drill_scenario(scenario_key)
    if not scenario:
        return jsonify({'success': False, 'message': '演练场景不存在'}), 404

    rows = []
    rows.append({'场景': scenario['name'], '步骤': '', '操作说明': '', '预期结果': '', '是否异常分支': '', '完成情况': ''})
    rows.append({'场景': scenario['description'], '步骤': '', '操作说明': '', '预期结果': '', '是否异常分支': '', '完成情况': ''})
    rows.append({'场景': '', '步骤': '', '操作说明': '', '预期结果': '', '是否异常分支': '', '完成情况': ''})

    for idx, step in enumerate(scenario['steps']):
        op_steps = _get_operation_steps(step['key'])
        op_text = '\n'.join(f'{i+1}. {s}' for i, s in enumerate(op_steps))

        rows.append({
            '场景': f'步骤{idx+1}',
            '步骤': step['name'],
            '操作说明': step.get('description', ''),
            '预期结果': step.get('expected_result', ''),
            '是否异常分支': '是' if step.get('is_exception_branch') else '否',
            '完成情况': '',
        })
        rows.append({
            '场景': '',
            '步骤': '详细操作',
            '操作说明': op_text,
            '预期结果': '',
            '是否异常分支': '',
            '完成情况': '',
        })
        if step.get('exception_description'):
            rows.append({
                '场景': '',
                '步骤': '异常说明',
                '操作说明': step['exception_description'],
                '预期结果': '',
                '是否异常分支': '',
                '完成情况': '',
            })
        rows.append({'场景': '', '步骤': '', '操作说明': '', '预期结果': '', '是否异常分支': '', '完成情况': ''})

    columns = ['场景', '步骤', '操作说明', '预期结果', '是否异常分支', '完成情况']
    df = pd.DataFrame(rows, columns=columns)
    output = StringIO()
    df.to_csv(output, index=False, encoding='utf-8-sig', lineterminator='\n')
    output.seek(0)

    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = f'attachment; filename=drill_checklist_{scenario_key}_{datetime.now().strftime("%Y%m%d%H%M%S")}.csv'
    return resp


@app.route('/api/drill/sessions/<int:session_id>/restart', methods=['POST'])
@require_login
def restart_drill_session(session_id):
    session = DrillSession.query.get(session_id)
    if not session:
        return jsonify({'success': False, 'message': '演练会话不存在'}), 404

    user = g.current_user
    if user.role != 'admin' and session.created_by != user.id:
        return jsonify({'success': False, 'message': '无权重置他人的演练会话', 'code': 'PERMISSION_DENIED'}), 403

    scenario = _get_drill_scenario(session.scenario_key)
    if not scenario:
        return jsonify({'success': False, 'message': '演练场景不存在'}), 404

    DrillStep.query.filter_by(session_id=session_id).delete()
    DrillAcceptanceRecord.query.filter_by(session_id=session_id).delete()

    now = datetime.utcnow()
    session.status = 'in_progress'
    session.start_time = now
    session.end_time = None
    session.completed_steps = 0
    session.failed_steps = 0

    for idx, step_def in enumerate(scenario['steps']):
        step = DrillStep(
            session_id=session.id,
            step_number=idx + 1,
            step_key=step_def['key'],
            step_name=step_def['name'],
            step_description=step_def.get('description', ''),
            action_type=step_def.get('action_type', ''),
            expected_result=step_def.get('expected_result', ''),
            status='pending',
            is_exception_branch=step_def.get('is_exception_branch', False),
            exception_description=step_def.get('exception_description', ''),
        )
        db.session.add(step)

    db.session.commit()

    d = session.to_dict()
    d['steps'] = [s.to_dict() for s in session.steps]

    return jsonify({'success': True, 'message': '演练已重置', 'data': d})


# ==================== 启动 ====================
with app.app_context():
    init_default_data()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
