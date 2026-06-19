import os
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # admin, operator, clerk
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'role': self.role,
            'created_at': self.created_at.isoformat()
        }


class SystemConfig(db.Model):
    __tablename__ = 'system_configs'
    id = db.Column(db.Integer, primary_key=True)
    config_key = db.Column(db.String(100), unique=True, nullable=False)
    config_value = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'))


class ImportBatch(db.Model):
    __tablename__ = 'import_batches'
    id = db.Column(db.Integer, primary_key=True)
    batch_no = db.Column(db.String(50), unique=True, nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    total_rows = db.Column(db.Integer, default=0)
    valid_rows = db.Column(db.Integer, default=0)
    invalid_rows = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='imported')  # imported, processing, completed
    imported_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    validation_results = db.relationship('ImportValidation', backref='batch', cascade='all, delete-orphan')
    labels = db.relationship('PriceLabel', backref='batch')


class ImportValidation(db.Model):
    __tablename__ = 'import_validations'
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey('import_batches.id'), nullable=False)
    row_number = db.Column(db.Integer, nullable=False)
    sku = db.Column(db.String(100))
    store = db.Column(db.String(100))
    original_price = db.Column(db.Float)
    promotion_price = db.Column(db.Float)
    effective_from = db.Column(db.String(50))
    effective_to = db.Column(db.String(50))
    template = db.Column(db.String(100))
    is_valid = db.Column(db.Boolean, default=False)
    error_message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class PriceLabel(db.Model):
    __tablename__ = 'price_labels'
    id = db.Column(db.Integer, primary_key=True)
    sku = db.Column(db.String(100), nullable=False)
    store = db.Column(db.String(100), nullable=False)
    original_price = db.Column(db.Float, nullable=False)
    promotion_price = db.Column(db.Float, nullable=False)
    effective_from = db.Column(db.DateTime, nullable=False)
    effective_to = db.Column(db.DateTime, nullable=False)
    template = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default='draft')  # draft, pending_approval, published, revoking, rolled_back, revoked
    version = db.Column(db.Integer, default=1)
    batch_id = db.Column(db.Integer, db.ForeignKey('import_batches.id'))
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    submitted_at = db.Column(db.DateTime)
    approved_at = db.Column(db.DateTime)
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    published_at = db.Column(db.DateTime)
    published_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    rolled_back_at = db.Column(db.DateTime)
    rolled_back_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    rollback_reason = db.Column(db.Text)
    previous_version_id = db.Column(db.Integer, db.ForeignKey('price_labels.id'))
    revoked_at = db.Column(db.DateTime)
    revoked_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    revoke_reason = db.Column(db.Text)

    __table_args__ = (
        db.Index('idx_store_sku', 'store', 'sku'),
        db.Index('idx_status', 'status'),
    )

    def to_dict(self, include_detail=False):
        result = {
            'id': self.id,
            'sku': self.sku,
            'store': self.store,
            'original_price': self.original_price,
            'promotion_price': self.promotion_price,
            'effective_from': self.effective_from.isoformat(),
            'effective_to': self.effective_to.isoformat(),
            'template': self.template,
            'status': self.status,
            'version': self.version,
            'batch_id': self.batch_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        if include_detail:
            result.update({
                'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
                'approved_at': self.approved_at.isoformat() if self.approved_at else None,
                'published_at': self.published_at.isoformat() if self.published_at else None,
                'rolled_back_at': self.rolled_back_at.isoformat() if self.rolled_back_at else None,
                'rollback_reason': self.rollback_reason,
                'previous_version_id': self.previous_version_id,
                'revoked_at': self.revoked_at.isoformat() if self.revoked_at else None,
                'revoked_by': self.revoked_by,
                'revoke_reason': self.revoke_reason,
            })
        return result


class RollbackHistory(db.Model):
    __tablename__ = 'rollback_history'
    id = db.Column(db.Integer, primary_key=True)
    label_id = db.Column(db.Integer, db.ForeignKey('price_labels.id'), nullable=False)
    from_version = db.Column(db.Integer, nullable=False)
    to_version = db.Column(db.Integer, nullable=False)
    from_status = db.Column(db.String(20))
    to_status = db.Column(db.String(20))
    reason = db.Column(db.Text)
    operated_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    label = db.relationship('PriceLabel', foreign_keys=[label_id])

    def to_dict(self):
        return {
            'id': self.id,
            'label_id': self.label_id,
            'sku': self.label.sku if self.label else None,
            'store': self.label.store if self.label else None,
            'from_version': self.from_version,
            'to_version': self.to_version,
            'from_status': self.from_status,
            'to_status': self.to_status,
            'reason': self.reason,
            'operated_by': self.operated_by,
            'created_at': self.created_at.isoformat()
        }


class PrintQueue(db.Model):
    __tablename__ = 'print_queues'
    id = db.Column(db.Integer, primary_key=True)
    label_id = db.Column(db.Integer, db.ForeignKey('price_labels.id'), nullable=False)
    store = db.Column(db.String(100), nullable=False)
    sku = db.Column(db.String(100), nullable=False)
    original_price = db.Column(db.Float, nullable=False)
    promotion_price = db.Column(db.Float, nullable=False)
    effective_from = db.Column(db.DateTime, nullable=False)
    effective_to = db.Column(db.DateTime, nullable=False)
    template = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, printed
    printed_at = db.Column(db.DateTime)
    printed_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    label = db.relationship('PriceLabel', foreign_keys=[label_id])

    def to_dict(self):
        return {
            'id': self.id,
            'label_id': self.label_id,
            'store': self.store,
            'sku': self.sku,
            'original_price': self.original_price,
            'promotion_price': self.promotion_price,
            'effective_from': self.effective_from.isoformat(),
            'effective_to': self.effective_to.isoformat(),
            'template': self.template,
            'status': self.status,
            'printed_at': self.printed_at.isoformat() if self.printed_at else None,
            'created_at': self.created_at.isoformat()
        }


class RevocationLog(db.Model):
    __tablename__ = 'revocation_logs'
    id = db.Column(db.Integer, primary_key=True)
    label_id = db.Column(db.Integer, db.ForeignKey('price_labels.id'), nullable=False)
    sku = db.Column(db.String(100), nullable=False)
    store = db.Column(db.String(100), nullable=False)
    original_status = db.Column(db.String(20), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    operated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    affected_print_queue_ids = db.Column(db.Text)

    label = db.relationship('PriceLabel', foreign_keys=[label_id])

    def to_dict(self):
        return {
            'id': self.id,
            'label_id': self.label_id,
            'sku': self.sku,
            'store': self.store,
            'original_status': self.original_status,
            'reason': self.reason,
            'operated_by': self.operated_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'affected_print_queue_ids': self.affected_print_queue_ids,
        }


class RevocationRequest(db.Model):
    __tablename__ = 'revocation_requests'
    id = db.Column(db.Integer, primary_key=True)
    label_id = db.Column(db.Integer, db.ForeignKey('price_labels.id'), nullable=False)
    sku = db.Column(db.String(100), nullable=False)
    store = db.Column(db.String(100), nullable=False)
    original_status = db.Column(db.String(20), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected
    offline_processing_note = db.Column(db.Text)
    requested_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    reviewed_at = db.Column(db.DateTime)
    review_comment = db.Column(db.Text)
    affected_print_queue_ids = db.Column(db.Text)

    label = db.relationship('PriceLabel', foreign_keys=[label_id])

    def to_dict(self):
        return {
            'id': self.id,
            'label_id': self.label_id,
            'sku': self.sku,
            'store': self.store,
            'original_status': self.original_status,
            'reason': self.reason,
            'status': self.status,
            'offline_processing_note': self.offline_processing_note,
            'requested_by': self.requested_by,
            'requested_at': self.requested_at.isoformat() if self.requested_at else None,
            'reviewed_by': self.reviewed_by,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'review_comment': self.review_comment,
            'affected_print_queue_ids': self.affected_print_queue_ids,
        }


class RevocationRequestLog(db.Model):
    __tablename__ = 'revocation_request_logs'
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey('revocation_requests.id'), nullable=False)
    label_id = db.Column(db.Integer, db.ForeignKey('price_labels.id'), nullable=False)
    sku = db.Column(db.String(100), nullable=False)
    store = db.Column(db.String(100), nullable=False)
    action = db.Column(db.String(20), nullable=False)  # submit, approve, reject
    original_status = db.Column(db.String(20), nullable=False)
    reason = db.Column(db.Text)
    operated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    affected_print_queue_ids = db.Column(db.Text)

    request = db.relationship('RevocationRequest', foreign_keys=[request_id])
    label = db.relationship('PriceLabel', foreign_keys=[label_id])

    def to_dict(self):
        return {
            'id': self.id,
            'request_id': self.request_id,
            'label_id': self.label_id,
            'sku': self.sku,
            'store': self.store,
            'action': self.action,
            'original_status': self.original_status,
            'reason': self.reason,
            'operated_by': self.operated_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'affected_print_queue_ids': self.affected_print_queue_ids,
        }


class HandoverSheet(db.Model):
    __tablename__ = 'handover_sheets'
    id = db.Column(db.Integer, primary_key=True)
    sheet_no = db.Column(db.String(50), unique=True, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    store = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default='pending')
    total_items = db.Column(db.Integer, default=0)
    remark = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    signed_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    signed_at = db.Column(db.DateTime)
    voided_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    voided_at = db.Column(db.DateTime)
    void_reason = db.Column(db.Text)
    has_conflict = db.Column(db.Boolean, default=False)
    conflict_checked_at = db.Column(db.DateTime)

    items = db.relationship('HandoverItem', backref='sheet', cascade='all, delete-orphan')

    __table_args__ = (
        db.Index('idx_handover_store', 'store'),
        db.Index('idx_handover_status', 'status'),
    )

    def to_dict(self, include_items=False):
        result = {
            'id': self.id,
            'sheet_no': self.sheet_no,
            'title': self.title,
            'store': self.store,
            'status': self.status,
            'total_items': self.total_items,
            'remark': self.remark,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'signed_by': self.signed_by,
            'signed_at': self.signed_at.isoformat() if self.signed_at else None,
            'voided_by': self.voided_by,
            'voided_at': self.voided_at.isoformat() if self.voided_at else None,
            'void_reason': self.void_reason,
            'has_conflict': self.has_conflict,
            'conflict_checked_at': self.conflict_checked_at.isoformat() if self.conflict_checked_at else None,
        }
        if include_items:
            result['items'] = [item.to_dict() for item in self.items]
        return result


class HandoverItem(db.Model):
    __tablename__ = 'handover_items'
    id = db.Column(db.Integer, primary_key=True)
    sheet_id = db.Column(db.Integer, db.ForeignKey('handover_sheets.id'), nullable=False)
    label_id = db.Column(db.Integer, db.ForeignKey('price_labels.id'), nullable=False)
    snapshot_sku = db.Column(db.String(100), nullable=False)
    snapshot_store = db.Column(db.String(100), nullable=False)
    snapshot_original_price = db.Column(db.Float, nullable=False)
    snapshot_promotion_price = db.Column(db.Float, nullable=False)
    snapshot_effective_from = db.Column(db.DateTime, nullable=False)
    snapshot_effective_to = db.Column(db.DateTime, nullable=False)
    snapshot_template = db.Column(db.String(100), nullable=False)
    snapshot_label_status = db.Column(db.String(20), nullable=False)
    snapshot_label_version = db.Column(db.Integer, nullable=False)
    print_status = db.Column(db.String(20), default='pending')
    is_conflict = db.Column(db.Boolean, default=False)
    conflict_reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    label = db.relationship('PriceLabel', foreign_keys=[label_id])

    __table_args__ = (
        db.Index('idx_handover_item_sheet', 'sheet_id'),
        db.UniqueConstraint('sheet_id', 'label_id', name='uq_sheet_label'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'sheet_id': self.sheet_id,
            'label_id': self.label_id,
            'snapshot_sku': self.snapshot_sku,
            'snapshot_store': self.snapshot_store,
            'snapshot_original_price': self.snapshot_original_price,
            'snapshot_promotion_price': self.snapshot_promotion_price,
            'snapshot_effective_from': self.snapshot_effective_from.isoformat() if self.snapshot_effective_from else None,
            'snapshot_effective_to': self.snapshot_effective_to.isoformat() if self.snapshot_effective_to else None,
            'snapshot_template': self.snapshot_template,
            'snapshot_label_status': self.snapshot_label_status,
            'snapshot_label_version': self.snapshot_label_version,
            'print_status': self.print_status,
            'is_conflict': self.is_conflict,
            'conflict_reason': self.conflict_reason,
            'current_label_status': self.label.status if self.label else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class HandoverLog(db.Model):
    __tablename__ = 'handover_logs'
    id = db.Column(db.Integer, primary_key=True)
    sheet_id = db.Column(db.Integer, db.ForeignKey('handover_sheets.id'), nullable=False)
    sheet_no = db.Column(db.String(50), nullable=False)
    action = db.Column(db.String(30), nullable=False)
    detail = db.Column(db.Text)
    operated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sheet = db.relationship('HandoverSheet', foreign_keys=[sheet_id])

    __table_args__ = (
        db.Index('idx_handover_log_sheet', 'sheet_id'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'sheet_id': self.sheet_id,
            'sheet_no': self.sheet_no,
            'action': self.action,
            'detail': self.detail,
            'operated_by': self.operated_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
