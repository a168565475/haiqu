from django.db.migrations.recorder import MigrationRecorder

from apps.core.api.concurrency import etag_for_instance
from .models import ACTIVE_STATES, RUNNING_STATES, CodexConnection, CodexOperation


def schema_is_ready():
    return MigrationRecorder.Migration.objects.filter(app='codex_connection', name='0001_initial').exists()


def get_connection():
    return CodexConnection.objects.first() or CodexConnection()


def connection_etag(connection):
    return '"codex-unconfigured"' if connection._state.adding else etag_for_instance(connection)


def current_operation(connection):
    if connection._state.adding:
        return None
    operations = CodexOperation.objects.filter(connection=connection, state__in=ACTIVE_STATES)
    return operations.filter(state__in=RUNNING_STATES).first() or operations.first()


def connection_snapshot(connection, actor_id=None):
    operation = current_operation(connection)
    return {
        'config_generation': connection.config_generation, 'status': connection.status,
        'selected_model': connection.selected_model, 'cli_version': connection.cli_version,
        'account': connection.account, 'models': connection.available_models, 'rate_limits': connection.rate_limits,
        'limits_updated_at': connection.limits_updated_at, 'last_checked_at': connection.last_checked_at,
        'last_test_at': connection.last_test_at, 'error_code': connection.error_code, 'paused': connection.paused,
        'operation': None if operation is None else {
            'id': str(operation.id), 'action': operation.action, 'state': operation.state,
            'actor_id': str(operation.actor_id),
            'can_cancel': (operation.action in ('login', 'switch') and operation.state in ('QUEUED', 'RUNNING')
                           and actor_id == operation.actor_id),
        },
    }
