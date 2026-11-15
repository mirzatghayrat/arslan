"""What is left of spawn_service's DTOs (the spawn REST endpoints went in C7c-4)."""
from server.db.models import Spawn
from server.services import spawn_service


# Moved from test_spawn_delete.py when C7c-3a removed DELETE /spawns/{id} and spawn_service.delete_spawn.
def test_to_summary_carries_is_default():
    sp = Spawn(id=1, name="B", domain_category="x", capabilities=[], system_prompt="x", is_default=True)
    assert spawn_service.to_summary(sp).is_default is True
