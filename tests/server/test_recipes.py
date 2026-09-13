import asyncio

from fastapi import HTTPException
import pytest
from sqlalchemy import select

from arslan.execution_budget import current
from server.api import recipes as api
from server.db.models import RecipeExecution, RecipeVersion, Run, Spawn
from server.services import recipes, run_registry


def spec(*, approval=False):
    return recipes.Spec(name="Research and synthesize", max_parallel=2, steps=[
        recipes.Step(key="a", name="Research A", spawn_id=1, task="A"),
        recipes.Step(key="b", name="Research B", spawn_id=2, task="B"),
        recipes.Step(key="c", name="Synthesis", spawn_id=1, task="Combine", depends_on=["a", "b"],
                     requires_approval=approval),
    ])


async def seed(maker, recipe=None):
    async with maker() as db:
        for i in (1, 2):
            db.add(Spawn(id=i, name=f"S{i}", domain_category="test", system_prompt="test"))
        version = RecipeVersion(key="research", version=1, name="Research", spec=(recipe or spec()).model_dump())
        db.add(version)
        await db.flush()
        execution = RecipeExecution(request_key="unique-request", recipe_id=version.id, input="synthetic input",
                                    status="queued", checkpoint={})
        db.add(execution)
        await db.commit()
        return execution.id, version.id


async def read(maker, id):
    async with maker() as db:
        return await db.get(RecipeExecution, id)


@pytest.mark.parametrize("change", ["cycle", "missing", "duplicate", "too_parallel"])
def test_recipe_graph_rejects_invalid_plans(change):
    data = spec().model_dump()
    if change == "cycle":
        data["steps"][0]["depends_on"] = ["c"]
    if change == "missing":
        data["steps"][0]["depends_on"] = ["unknown"]
    if change == "duplicate":
        data["steps"][1]["key"] = "a"
    if change == "too_parallel":
        data["max_parallel"] = 5
    with pytest.raises(ValueError):
        recipes.Spec.model_validate(data)


async def test_dag_executes_parallel_then_dependency_with_shared_budget(execution_db, monkeypatch):
    id, _ = await seed(execution_db)
    entered, finished, budget_ids = [], [], []
    both = asyncio.Event()

    async def dispatch(cid, **kwargs):
        task = kwargs["task_brief"].split("\n")[0]
        assert kwargs["include_history"] is False and kwargs["persist"] is False
        assert kwargs["allow_escalation"] is False and kwargs["run_id"] > 0
        budget_ids.append(current().id)
        entered.append(task)
        if task in {"A", "B"}:
            if len(entered) == 2:
                both.set()
            await asyncio.wait_for(both.wait(), 2)
        else:
            assert set(finished) == {"A", "B"}
            assert "output A" in kwargs["task_brief"] and "output B" in kwargs["task_brief"]
        finished.append(task)
        kwargs["on_chunk"](f"output {task}")
        return {"full_output": f"output {task}"}
    monkeypatch.setattr(recipes.dispatcher, "dispatch", dispatch)
    await recipes.execute(id)
    row = await read(execution_db, id)
    assert row.status == "completed" and len(set(budget_ids)) == 1
    assert row.checkpoint["steps"]["c"]["output"] == "output Combine"
    async with execution_db() as db:
        runs = (await db.execute(select(Run))).scalars().all()
    assert len(runs) == 4 and all(r.status == "completed" for r in runs)
    assert {r.kind for r in runs} == {"recipe", "recipe_step"}


async def test_approval_resume_reuses_completed_steps(execution_db, monkeypatch):
    id, _ = await seed(execution_db, spec(approval=True))
    calls = []
    async def dispatch(cid, **kwargs):
        calls.append(kwargs["task_brief"].split("\n")[0])
        return {"full_output": calls[-1]}
    monkeypatch.setattr(recipes.dispatcher, "dispatch", dispatch)
    await recipes.execute(id)
    assert (await read(execution_db, id)).status == "waiting_approval"
    assert sorted(calls) == ["A", "B"]
    launched = []
    monkeypatch.setattr(recipes, "launch", launched.append)
    await api.resume_execution(id, api.Resume(approve_steps=["c"]))
    assert launched == [id]
    await recipes.execute(id)
    assert calls.count("A") == calls.count("B") == calls.count("Combine") == 1
    assert (await read(execution_db, id)).status == "completed"


async def test_failure_blocks_dependents_and_requires_explicit_retry(execution_db, monkeypatch):
    id, _ = await seed(execution_db)
    calls = []
    async def dispatch(cid, **kwargs):
        task = kwargs["task_brief"].split("\n")[0]
        calls.append(task)
        if task == "A":
            raise RuntimeError("synthetic failure")
        await asyncio.Event().wait()
    monkeypatch.setattr(recipes.dispatcher, "dispatch", dispatch)
    with pytest.raises(ExceptionGroup):
        await recipes.execute(id)
    row = await read(execution_db, id)
    assert row.status == "failed" and "Combine" not in calls
    with pytest.raises(HTTPException) as error:
        await api.resume_execution(id, api.Resume())
    assert error.value.status_code == 409
    assert not run_registry.active_for(f"recipe-{id}")


async def test_parent_run_cancel_stops_children_and_records_interruption(execution_db, monkeypatch):
    id, _ = await seed(execution_db)
    entered = asyncio.Event()
    async def dispatch(cid, **kwargs):
        entered.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(recipes.dispatcher, "dispatch", dispatch)
    task = asyncio.create_task(recipes.execute(id))
    await entered.wait()
    row = await read(execution_db, id)
    assert run_registry.cancel(row.run_id)
    await asyncio.wait_for(task, 2)
    assert (await read(execution_db, id)).status == "interrupted"
    assert not run_registry.active_for(f"recipe-{id}")


async def test_boot_marks_execution_interrupted_without_launching(execution_db, monkeypatch):
    id, _ = await seed(execution_db)
    launched = []
    monkeypatch.setattr(recipes, "launch", launched.append)
    assert await recipes.mark_interrupted() == 1
    assert (await read(execution_db, id)).status == "interrupted" and launched == []


async def test_versions_are_immutable_and_start_requests_idempotent(execution_db, monkeypatch):
    _, version_id = await seed(execution_db)
    saved = await api.save_version("research", spec(approval=True))
    assert saved["version"] == 2
    async with execution_db() as db:
        old = await db.get(RecipeVersion, version_id)
    assert old.spec["steps"][2]["requires_approval"] is False
    launched = []
    monkeypatch.setattr(recipes, "launch", launched.append)
    body = api.Start(recipe_id=saved["id"], input="test", request_key="idempotent-start")
    first, second = await api.start_execution(body), await api.start_execution(body)
    assert first["id"] == second["id"] and launched == [first["id"]]
    with pytest.raises(HTTPException):
        await api.start_execution(body.model_copy(update={"input": "different"}))


async def test_http_boundary_requires_auth_and_validates_recipe(execution_db, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from server import auth
    monkeypatch.setattr(auth, "active_token", lambda: "test-access-token")
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/v1/recipes")).status_code == 401
        headers = {"Authorization": "Bearer test-access-token"}
        assert (await client.get("/api/v1/recipes", headers=headers)).status_code == 200
        response = await client.post("/api/v1/recipes/research/versions", headers=headers, json=spec().model_dump())
        assert response.status_code == 422 and response.json()["detail"]["code"] == "recipes.spawn_missing"
        assert (await client.post("/api/v1/recipe-executions", headers=headers,
                                 json={"recipe_id": 1, "input": "task", "request_key": "request-123", "unsafe": True})).status_code == 422
