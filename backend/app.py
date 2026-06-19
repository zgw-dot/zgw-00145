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
    PriceLabel, RollbackHistory, PrintQueue
)

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
            PriceLabel.status.in_(['pending_approval', 'published']),
            PriceLabel.effective_from < effective_to,
            PriceLabel.effective_to > effective_from
        ).first()
        if overlap:
            errors.append(f'与已有价签(ID:{overlap.id})生效时段重叠')

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


def is_in_publish_window():
    cfg = get_config('publish_window', {'enabled': False})
    if not cfg or not cfg.get('enabled'):
        return True
    now = datetime.now()
    if cfg.get('weekdays_only') and now.weekday() >= 5:
        return False
    hour = now.hour
    return cfg.get('start_hour', 0) <= hour < cfg.get('end_hour', 24)


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

    return jsonify({
        'success': True,
        'data': {
            'label': label.to_dict(include_detail=True),
            'rollback_history': [h.to_dict() for h in history],
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
        approved_set = {}

        for lid in label_ids:
            label = PriceLabel.query.get(lid)
            if not label:
                failed.append({'id': lid, 'reason': '价签不存在'})
                continue
            if label.status != 'pending_approval':
                failed.append({'id': lid, 'reason': f'状态为{label.status}，不能审批'})
                continue

            overlap_db = PriceLabel.query.filter(
                PriceLabel.sku == label.sku,
                PriceLabel.store == label.store,
                PriceLabel.id != label.id,
                PriceLabel.status == 'published',
                PriceLabel.effective_from < label.effective_to,
                PriceLabel.effective_to > label.effective_from
            ).first()
            if overlap_db:
                failed.append({'id': lid, 'reason': f'与已发布价签(ID:{overlap_db.id})生效时段重叠'})
                continue

            key = f'{label.store}|{label.sku}'
            batch_overlap = False
            if key in approved_set:
                for other in approved_set[key]:
                    if other.effective_from < label.effective_to and other.effective_to > label.effective_from:
                        failed.append({'id': lid, 'reason': f'与本次同批通过的价签(ID:{other.id})生效时段重叠'})
                        batch_overlap = True
                        break
            if batch_overlap:
                continue

            if key not in approved_set:
                approved_set[key] = []
            approved_set[key].append(label)

        for key, labels in approved_set.items():
            for label in labels:
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
        db.session.commit()

        return jsonify({'success': True, 'message': '回滚成功'})


# ==================== 打印清单接口 ====================
@app.route('/api/print-queue', methods=['GET'])
@require_login
def list_print_queue():
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 50, type=int)
    status = request.args.get('status', '')
    store = request.args.get('store', '')

    query = PrintQueue.query
    if status:
        query = query.filter_by(status=status)
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
        'rolled_back': '已回滚'
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
            '上一版本ID': l.previous_version_id or '',
            '关联批次ID': l.batch_id or '',
        })

    df = pd.DataFrame(rows)
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

    query = PrintQueue.query
    if status:
        query = query.filter_by(status=status)
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

    df = pd.DataFrame(rows)
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
        'rolled_back': '已回滚'
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

    df = pd.DataFrame(rows)
    output = StringIO()
    df.to_csv(output, index=False, encoding='utf-8-sig', lineterminator='\n')
    output.seek(0)

    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = f'attachment; filename=rollback_history_{datetime.now().strftime("%Y%m%d%H%M%S")}.csv'
    return resp


# ==================== 统计接口 ====================
@app.route('/api/stats/overview', methods=['GET'])
@require_login
def stats_overview():
    total = PriceLabel.query.count()
    draft = PriceLabel.query.filter_by(status='draft').count()
    pending = PriceLabel.query.filter_by(status='pending_approval').count()
    published = PriceLabel.query.filter_by(status='published').count()
    rolled_back = PriceLabel.query.filter_by(status='rolled_back').count()
    pending_print = PrintQueue.query.filter_by(status='pending').count()
    rollback_count = RollbackHistory.query.count()

    return jsonify({
        'success': True,
        'data': {
            'total': total,
            'draft': draft,
            'pending_approval': pending,
            'published': published,
            'rolled_back': rolled_back,
            'pending_print': pending_print,
            'rollback_count': rollback_count,
            'in_publish_window': is_in_publish_window()
        }
    })


# ==================== 启动 ====================
with app.app_context():
    init_default_data()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
