from datetime import datetime
from models import db, PriceLabel, SystemConfig


def get_config(key, default=None):
    cfg = SystemConfig.query.filter_by(config_key=key).first()
    if cfg:
        try:
            import json
            return json.loads(cfg.config_value)
        except (Exception,):
            return cfg.config_value
    return default


def is_in_publish_window():
    cfg = get_config('publish_window', {'enabled': False})
    if not cfg or not cfg.get('enabled'):
        return True, ''
    now = datetime.now()
    if cfg.get('weekdays_only') and now.weekday() >= 5:
        return False, '发布窗口限制：仅工作日允许发布'
    hour = now.hour
    start = cfg.get('start_hour', 0)
    end = cfg.get('end_hour', 24)
    if not (start <= hour < end):
        return False, f'发布窗口限制：当前不在发布时段({start}:00-{end}:00)内'
    return True, ''


def check_publish_approval(label_ids):
    labels_by_id = {}
    for lid in label_ids:
        label = PriceLabel.query.get(lid)
        if label:
            labels_by_id[lid] = label

    window_ok, window_reason = is_in_publish_window()

    approved_set = {}
    results = {}

    for lid in label_ids:
        label = labels_by_id.get(lid)
        if not label:
            results[lid] = {
                'group': 'config_restricted',
                'label_id': lid,
                'sku': '',
                'store': '',
                'effective_from': '',
                'effective_to': '',
                'risk_reason': '价签不存在',
                'suggested_action': '检查价签ID是否正确',
            }
            continue

        info = {
            'label_id': lid,
            'sku': label.sku,
            'store': label.store,
            'effective_from': label.effective_from.isoformat() if label.effective_from else '',
            'effective_to': label.effective_to.isoformat() if label.effective_to else '',
        }

        if label.status != 'pending_approval':
            results[lid] = {
                **info,
                'group': 'config_restricted',
                'risk_reason': f'价签状态为"{label.status}"，不是待审状态',
                'suggested_action': '仅待审状态的价签可审批发布',
            }
            continue

        if not window_ok:
            results[lid] = {
                **info,
                'group': 'config_restricted',
                'risk_reason': window_reason,
                'suggested_action': '等待发布窗口开放后再提交审批',
            }
            continue

        overlap_db = PriceLabel.query.filter(
            PriceLabel.sku == label.sku,
            PriceLabel.store == label.store,
            PriceLabel.id != label.id,
            PriceLabel.status.in_(['published', 'revoking']),
            PriceLabel.effective_from < label.effective_to,
            PriceLabel.effective_to > label.effective_from
        ).first()
        if overlap_db:
            status_label = {
                'published': '已发布',
                'revoking': '撤销中'
            }.get(overlap_db.status, overlap_db.status)
            results[lid] = {
                **info,
                'group': 'conflict',
                'risk_reason': f'与{status_label}价签(ID:{overlap_db.id})同门店同SKU生效时段重叠',
                'suggested_action': f'处理或调整{status_label}价签(ID:{overlap_db.id})的时段后再审批',
            }
            continue

        key = f'{label.store}|{label.sku}'
        batch_overlap = False
        if key in approved_set:
            for other in approved_set[key]:
                if other.effective_from < label.effective_to and other.effective_to > label.effective_from:
                    results[lid] = {
                        **info,
                        'group': 'conflict',
                        'risk_reason': f'与本次批量中价签(ID:{other.id})同门店同SKU生效时段重叠',
                        'suggested_action': f'移除其中一条或调整时段，避免同时审批冲突的价签',
                    }
                    batch_overlap = True
                    break
        if batch_overlap:
            continue

        if key not in approved_set:
            approved_set[key] = []
        approved_set[key].append(label)

        results[lid] = {
            **info,
            'group': 'publishable',
            'risk_reason': '',
            'suggested_action': '可以直接审批发布',
        }

    return results
