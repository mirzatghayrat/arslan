"""0049: authenticated per-conversation project and memory controls."""


def upgrade_sync(connection):
    from server.db.models import ContextReceiptRecord, ConversationContext
    ConversationContext.__table__.create(connection, checkfirst=True)
    ContextReceiptRecord.__table__.create(connection, checkfirst=True)
