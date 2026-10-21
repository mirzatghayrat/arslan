"""A memory v2 retrieval scope for tests: a project with collections, and a turn context bound to it.

Under memory v2, knowledge.retrieve_scoped reads only the collections of the turn's project (0.1.63 C2a-2
removed the v1 scopes: an expert's own well, and "all shared collections" for Arslan).
"""
from server.db.companion_models import Project
from server.services import personal_context as pc


def context(project_id: str = "p-test", **overrides) -> pc.TaskMemoryContext:
    fields = dict(task_id="t", run_id="r", project_id=project_id, model_is_local=True, cloud_memory_allowed=True)
    fields.update(overrides)
    return pc.TaskMemoryContext(**fields)


def project(collection_ids, project_id: str = "p-test") -> Project:
    return Project(id=project_id, owner_id="local", name="test", collection_ids=list(collection_ids),
                   status="active")
