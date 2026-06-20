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
    assigned_to = db.Column(db.Integer, db.ForeignKey('users.id'))
    assigned_at = db.Column(db.DateTime)
    assigned_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    view_scope = db.Column(db.String(20), default='assigned')  # assigned, store_all, role_all, specific
    revoke_status = db.Column(db.String(20), default='none')  # none, revoking, revoked, reopened
    revoked_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    revoked_at = db.Column(db.DateTime)
    revoke_reason = db.Column(db.Text)
    reopened_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    reopened_at = db.Column(db.DateTime)

    items = db.relationship('HandoverItem', backref='sheet', cascade='all, delete-orphan')
    authorizations = db.relationship('HandoverAuthorization', backref='sheet', cascade='all, delete-orphan')
    receipts = db.relationship('HandoverReceipt', backref='sheet', cascade='all, delete-orphan')
    audit_logs = db.relationship('HandoverAuditLog', backref='sheet', cascade='all, delete-orphan')

    __table_args__ = (
        db.Index('idx_handover_store', 'store'),
        db.Index('idx_handover_status', 'status'),
        db.Index('idx_handover_assigned', 'assigned_to'),
        db.Index('idx_handover_revoke', 'revoke_status'),
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
            'assigned_to': self.assigned_to,
            'assigned_at': self.assigned_at.isoformat() if self.assigned_at else None,
            'assigned_by': self.assigned_by,
            'view_scope': self.view_scope,
            'revoke_status': self.revoke_status,
            'revoked_by': self.revoked_by,
            'revoked_at': self.revoked_at.isoformat() if self.revoked_at else None,
            'revoke_reason': self.revoke_reason,
            'reopened_by': self.reopened_by,
            'reopened_at': self.reopened_at.isoformat() if self.reopened_at else None,
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


class DrillDemoData(db.Model):
    __tablename__ = 'drill_demo_data'
    id = db.Column(db.Integer, primary_key=True)
    data_key = db.Column(db.String(100), unique=True, nullable=False)
    data_name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    data_type = db.Column(db.String(50), default='labels')
    content = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    imported_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    imported_at = db.Column(db.DateTime, default=datetime.utcnow)
    import_batch_id = db.Column(db.Integer)

    def to_dict(self):
        return {
            'id': self.id,
            'data_key': self.data_key,
            'data_name': self.data_name,
            'description': self.description,
            'data_type': self.data_type,
            'is_active': self.is_active,
            'imported_by': self.imported_by,
            'imported_at': self.imported_at.isoformat() if self.imported_at else None,
            'import_batch_id': self.import_batch_id,
        }


class DrillSession(db.Model):
    __tablename__ = 'drill_sessions'
    id = db.Column(db.Integer, primary_key=True)
    session_no = db.Column(db.String(50), unique=True, nullable=False)
    title = db.Column(db.String(200), nullable=False)
    scenario_key = db.Column(db.String(100), nullable=False)
    scenario_name = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), default='in_progress')
    total_steps = db.Column(db.Integer, default=0)
    completed_steps = db.Column(db.Integer, default=0)
    failed_steps = db.Column(db.Integer, default=0)
    start_time = db.Column(db.DateTime, default=datetime.utcnow)
    end_time = db.Column(db.DateTime)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    remark = db.Column(db.Text)
    demo_data_key = db.Column(db.String(100))

    steps = db.relationship('DrillStep', backref='session', cascade='all, delete-orphan', order_by='DrillStep.step_number')
    acceptance_records = db.relationship('DrillAcceptanceRecord', backref='session', cascade='all, delete-orphan')

    __table_args__ = (
        db.Index('idx_drill_session_status', 'status'),
        db.Index('idx_drill_session_role', 'role'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'session_no': self.session_no,
            'title': self.title,
            'scenario_key': self.scenario_key,
            'scenario_name': self.scenario_name,
            'role': self.role,
            'status': self.status,
            'total_steps': self.total_steps,
            'completed_steps': self.completed_steps,
            'failed_steps': self.failed_steps,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'remark': self.remark,
            'demo_data_key': self.demo_data_key,
        }


class DrillStep(db.Model):
    __tablename__ = 'drill_steps'
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('drill_sessions.id'), nullable=False)
    step_number = db.Column(db.Integer, nullable=False)
    step_key = db.Column(db.String(100), nullable=False)
    step_name = db.Column(db.String(200), nullable=False)
    step_description = db.Column(db.Text)
    action_type = db.Column(db.String(50))
    expected_result = db.Column(db.Text)
    actual_result = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')
    request_data = db.Column(db.Text)
    response_data = db.Column(db.Text)
    error_message = db.Column(db.Text)
    completed_at = db.Column(db.DateTime)
    duration_ms = db.Column(db.Integer)
    is_exception_branch = db.Column(db.Boolean, default=False)
    exception_description = db.Column(db.Text)

    __table_args__ = (
        db.UniqueConstraint('session_id', 'step_number', name='uq_drill_step_session_number'),
        db.UniqueConstraint('session_id', 'step_key', name='uq_drill_step_session_key'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'session_id': self.session_id,
            'step_number': self.step_number,
            'step_key': self.step_key,
            'step_name': self.step_name,
            'step_description': self.step_description,
            'action_type': self.action_type,
            'expected_result': self.expected_result,
            'actual_result': self.actual_result,
            'status': self.status,
            'request_data': self.request_data,
            'response_data': self.response_data,
            'error_message': self.error_message,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'duration_ms': self.duration_ms,
            'is_exception_branch': self.is_exception_branch,
            'exception_description': self.exception_description,
        }


class DrillAcceptanceRecord(db.Model):
    __tablename__ = 'drill_acceptance_records'
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('drill_sessions.id'), nullable=False)
    step_id = db.Column(db.Integer, db.ForeignKey('drill_steps.id'))
    acceptance_item = db.Column(db.String(200), nullable=False)
    acceptance_category = db.Column(db.String(50))
    passed = db.Column(db.Boolean, default=False)
    expected_value = db.Column(db.Text)
    actual_value = db.Column(db.Text)
    remark = db.Column(db.Text)
    checked_at = db.Column(db.DateTime, default=datetime.utcnow)
    checked_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    step = db.relationship('DrillStep', foreign_keys=[step_id])

    def to_dict(self):
        return {
            'id': self.id,
            'session_id': self.session_id,
            'step_id': self.step_id,
            'acceptance_item': self.acceptance_item,
            'acceptance_category': self.acceptance_category,
            'passed': self.passed,
            'expected_value': self.expected_value,
            'actual_value': self.actual_value,
            'remark': self.remark,
            'checked_at': self.checked_at.isoformat() if self.checked_at else None,
            'checked_by': self.checked_by,
        }


class HandoverAuthorization(db.Model):
    __tablename__ = 'handover_authorizations'
    id = db.Column(db.Integer, primary_key=True)
    sheet_id = db.Column(db.Integer, db.ForeignKey('handover_sheets.id'), nullable=False)
    auth_token = db.Column(db.String(100), unique=True, nullable=False)
    token_type = db.Column(db.String(20), default='sign')  # sign, view, receipt
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    role_restriction = db.Column(db.String(20))
    store_restriction = db.Column(db.String(100))
    expires_at = db.Column(db.DateTime, nullable=False)
    is_used = db.Column(db.Boolean, default=False)
    used_at = db.Column(db.DateTime)
    used_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    remark = db.Column(db.Text)
    one_time = db.Column(db.Boolean, default=True)
    revoked = db.Column(db.Boolean, default=False)
    revoked_at = db.Column(db.DateTime)
    revoked_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    revoke_reason = db.Column(db.Text)
    generation_id = db.Column(db.String(100))

    user = db.relationship('User', foreign_keys=[user_id])

    __table_args__ = (
        db.Index('idx_auth_sheet', 'sheet_id'),
        db.Index('idx_auth_token', 'auth_token'),
        db.Index('idx_auth_user', 'user_id'),
        db.Index('idx_auth_expires', 'expires_at'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'sheet_id': self.sheet_id,
            'auth_token': self.auth_token,
            'token_type': self.token_type,
            'user_id': self.user_id,
            'user_name': self.user.username if self.user else None,
            'role_restriction': self.role_restriction,
            'store_restriction': self.store_restriction,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'is_used': self.is_used,
            'used_at': self.used_at.isoformat() if self.used_at else None,
            'used_by': self.used_by,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'remark': self.remark,
            'one_time': self.one_time,
            'revoked': self.revoked,
            'revoked_at': self.revoked_at.isoformat() if self.revoked_at else None,
            'revoked_by': self.revoked_by,
            'revoke_reason': self.revoke_reason,
            'generation_id': self.generation_id,
        }


class HandoverReceipt(db.Model):
    __tablename__ = 'handover_receipts'
    id = db.Column(db.Integer, primary_key=True)
    sheet_id = db.Column(db.Integer, db.ForeignKey('handover_sheets.id'), nullable=False)
    receipt_no = db.Column(db.String(50), unique=True, nullable=False)
    authorization_id = db.Column(db.Integer, db.ForeignKey('handover_authorizations.id'))
    signed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    signed_at = db.Column(db.DateTime, default=datetime.utcnow)
    signer_ip = db.Column(db.String(50))
    signer_user_agent = db.Column(db.String(500))
    signer_remark = db.Column(db.Text)
    item_count = db.Column(db.Integer, default=0)
    sheet_snapshot = db.Column(db.Text)
    items_snapshot = db.Column(db.Text)
    receipt_hash = db.Column(db.String(128))
    export_count = db.Column(db.Integer, default=0)
    last_exported_at = db.Column(db.DateTime)

    authorization = db.relationship('HandoverAuthorization', foreign_keys=[authorization_id])
    signer = db.relationship('User', foreign_keys=[signed_by])

    __table_args__ = (
        db.Index('idx_receipt_sheet', 'sheet_id'),
        db.Index('idx_receipt_no', 'receipt_no'),
        db.Index('idx_receipt_signed_by', 'signed_by'),
    )

    def to_dict(self, include_snapshot=False):
        result = {
            'id': self.id,
            'sheet_id': self.sheet_id,
            'receipt_no': self.receipt_no,
            'authorization_id': self.authorization_id,
            'signed_by': self.signed_by,
            'signed_by_name': self.signer.username if self.signer else None,
            'signed_at': self.signed_at.isoformat() if self.signed_at else None,
            'signer_ip': self.signer_ip,
            'signer_user_agent': self.signer_user_agent,
            'signer_remark': self.signer_remark,
            'item_count': self.item_count,
            'receipt_hash': self.receipt_hash,
            'export_count': self.export_count,
            'last_exported_at': self.last_exported_at.isoformat() if self.last_exported_at else None,
        }
        if include_snapshot:
            result['sheet_snapshot'] = self.sheet_snapshot
            result['items_snapshot'] = self.items_snapshot
        return result


class HandoverAuditLog(db.Model):
    __tablename__ = 'handover_audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    sheet_id = db.Column(db.Integer, db.ForeignKey('handover_sheets.id'))
    sheet_no = db.Column(db.String(50))
    authorization_id = db.Column(db.Integer, db.ForeignKey('handover_authorizations.id'))
    action = db.Column(db.String(50), nullable=False)
    result = db.Column(db.String(20), nullable=False)  # allowed, blocked
    block_reason = db.Column(db.String(100))
    block_code = db.Column(db.String(50))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    user_name = db.Column(db.String(50))
    user_role = db.Column(db.String(20))
    client_ip = db.Column(db.String(50))
    user_agent = db.Column(db.String(500))
    request_path = db.Column(db.String(500))
    request_method = db.Column(db.String(10))
    request_params = db.Column(db.Text)
    request_body = db.Column(db.Text)
    response_status = db.Column(db.Integer)
    response_message = db.Column(db.Text)
    detail = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index('idx_audit_sheet', 'sheet_id'),
        db.Index('idx_audit_action', 'action'),
        db.Index('idx_audit_result', 'result'),
        db.Index('idx_audit_user', 'user_id'),
        db.Index('idx_audit_created', 'created_at'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'sheet_id': self.sheet_id,
            'sheet_no': self.sheet_no,
            'authorization_id': self.authorization_id,
            'action': self.action,
            'result': self.result,
            'block_reason': self.block_reason,
            'block_code': self.block_code,
            'user_id': self.user_id,
            'user_name': self.user_name,
            'user_role': self.user_role,
            'client_ip': self.client_ip,
            'user_agent': self.user_agent,
            'request_path': self.request_path,
            'request_method': self.request_method,
            'request_params': self.request_params,
            'request_body': self.request_body,
            'response_status': self.response_status,
            'response_message': self.response_message,
            'detail': self.detail,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
