"""Shared transactional local boot; no seeders, workers or provider calls."""


async def initialize(engine):
    from server.db.models import Base
    from server.db.migrations import runner
    from server.services import crypto_boot
    from server.services.memory_activation import activate_sync

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(runner.apply_pending)
        # Salt adoption precedes decryption; verified legacy writes and memory
        # activation share this transaction, before any background/request work.
        await connection.run_sync(crypto_boot.resolve_and_adopt_salt)
        await connection.run_sync(crypto_boot.migrate_legacy_ciphertext)
        await connection.run_sync(activate_sync)
