"""Arslan CLI — entry point wiring up all modules."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from arslan import __version__
from arslan.core.dialogue import DialogueEngine
from arslan.core.evolution import EvolutionEngine
from arslan.models import SpawnBlueprint, SpawnRequirements
from arslan.spawn.evolve import apply_tier1_evolution, consolidate_evolution, reset_evolution
from arslan.spawn.manager import SpawnManager

console = Console()


# ---------------------------------------------------------------------------
# Main group
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(__version__, prog_name="Arslan")
def main() -> None:
    """🐆 Arslan — 你的专属 Agent 建造师"""


# ---------------------------------------------------------------------------
# list command
# ---------------------------------------------------------------------------


@main.command("list")
@click.option("--spawns-dir", type=click.Path(), default="spawns", show_default=True)
def list_spawns(spawns_dir: str) -> None:
    """查看所有已创建的分身。"""
    manager = SpawnManager(Path(spawns_dir))
    spawns = manager.list_spawns()

    if not spawns:
        console.print("[yellow]尚未创建任何分身。运行 [bold]arslan new[/bold] 来创建第一个！[/yellow]")
        return

    table = Table(title="已创建的分身", show_header=True, header_style="bold cyan")
    table.add_column("名称", style="bold")
    table.add_column("领域")
    table.add_column("模板")
    table.add_column("生成级别")
    table.add_column("路径", style="dim")

    for spawn in spawns:
        table.add_row(
            spawn.get("name", "—"),
            spawn.get("domain", "—"),
            spawn.get("template_used") or "—",
            str(spawn.get("generation_level", 1)),
            spawn.get("path", "—"),
        )

    console.print(table)


# ---------------------------------------------------------------------------
# new command
# ---------------------------------------------------------------------------


def _run_generator(manager: SpawnManager, blueprint: SpawnBlueprint, runtime: str) -> Path:
    """Select the generation path: lightweight skill-pack (default) or heavy spawn."""
    if runtime == "heavy":
        return manager.generate(blueprint)
    return manager.generate_skillpack(blueprint)


@main.command()
@click.option("--spawns-dir", type=click.Path(), default="spawns", show_default=True)
@click.option(
    "--runtime",
    type=click.Choice(["skillpack", "heavy"]),
    default="skillpack",
    show_default=True,
    help="生成形态：skillpack（轻量，默认）或 heavy（自带运行时/Docker）。",
)
def new(spawns_dir: str, runtime: str) -> None:
    """对话式创建新分身。"""
    console.print("\n[bold cyan]🐆 欢迎使用 Arslan 分身建造师！[/bold cyan]")
    console.print("我会通过几个问题帮你创建专属 AI 分身。\n")

    engine = DialogueEngine()

    # Run dialogue loop
    while not engine.state.is_finished:
        question = engine.get_next_question()
        if question is None:
            break

        # Display question
        console.print(f"[bold green]{question.text}[/bold green]")

        if question.hint:
            console.print(f"[dim]提示: {question.hint}[/dim]")

        if question.options:
            for i, opt in enumerate(question.options, 1):
                console.print(f"  [cyan]{i}.[/cyan] {opt}")

        if question.multi_select:
            console.print("[dim]（可输入多个选项，用逗号或空格分隔）[/dim]")

        # Get user input
        user_input = click.prompt("你的回答", default="", show_default=False).strip()

        if not user_input:
            console.print("[yellow]输入不能为空，请重试。[/yellow]")
            continue

        engine.process_user_input(user_input)

    # Summary
    console.print("\n" + engine.get_summary())
    console.print()

    req = engine.state.requirements

    # Try template matching
    template_used: str | None = None
    try:
        from arslan.templates.library import TemplateLibrary
        library = TemplateLibrary()
        library.load_official()
        if req.domain:
            matches = library.search_by_domain(req.domain.full_domain)
            if not matches:
                matches = library.search_by_domain(req.domain.category)
            if matches:
                template_used = matches[0].name
    except Exception:  # noqa: BLE001
        pass

    # Build a minimal blueprint (no LLM required)
    blueprint = SpawnBlueprint(
        requirements=req,
        tools=[],
        system_prompt=_build_system_prompt(req),
        workflow_steps=[],
        template_used=template_used,
        generation_level=1,
    )

    # Generate spawn
    manager = SpawnManager(Path(spawns_dir))
    try:
        spawn_path = _run_generator(manager, blueprint, runtime)
        console.print(f"[bold green]✅ 分身已成功创建！[/bold green]")
        console.print(f"[dim]路径: {spawn_path}[/dim]")
        console.print()
        console.print("启动你的分身：")
        console.print(f"  [bold]arslan run {req.spawn_name}[/bold]")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]创建分身时出错: {exc}[/red]")
        sys.exit(1)


def _build_system_prompt(req: SpawnRequirements) -> str:
    """Build a basic system prompt from requirements."""
    parts: list[str] = []
    if req.persona and req.persona.role:
        parts.append(f"你是{req.persona.role}。")
    if req.persona and req.persona.tone:
        parts.append(f"风格：{req.persona.tone}。")
    if req.domain:
        parts.append(f"专注领域：{req.domain.full_domain}。")
    if req.capabilities:
        parts.append(f"核心能力：{', '.join(req.capabilities)}。")
    return " ".join(parts) if parts else "你是一个有帮助的 AI 助手。"


# ---------------------------------------------------------------------------
# run command
# ---------------------------------------------------------------------------


@main.command()
@click.argument("name")
@click.option("--spawns-dir", type=click.Path(), default="spawns", show_default=True)
@click.option("--port", type=int, default=8080, show_default=True, help="Web 服务端口。")
def run(name: str, spawns_dir: str, port: int) -> None:
    """启动一个分身。"""
    manager = SpawnManager(Path(spawns_dir))
    spawn_path = manager.get_spawn_path(name)

    if spawn_path is None:
        console.print(f"[red]找不到分身 '[bold]{name}[/bold]'。[/red]")
        console.print(f"[dim]请先运行 arslan new 创建分身，或检查 --spawns-dir 路径。[/dim]")
        sys.exit(1)

    main_py = spawn_path / "main.py"
    if not main_py.exists():
        console.print(f"[red]分身目录中缺少 main.py: {spawn_path}[/red]")
        sys.exit(1)

    console.print(f"[bold cyan]🚀 启动分身 '{name}' (端口 {port})...[/bold cyan]")
    console.print(f"[dim]{main_py}[/dim]\n")

    try:
        subprocess.run(
            [sys.executable, str(main_py), "--port", str(port)],
            cwd=str(spawn_path),
            check=True,
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]已停止。[/yellow]")
    except subprocess.CalledProcessError as exc:
        console.print(f"[red]分身退出，返回码: {exc.returncode}[/red]")
        sys.exit(exc.returncode)


# ---------------------------------------------------------------------------
# evolve command
# ---------------------------------------------------------------------------


@main.command()
@click.argument("name")
@click.option("--spawns-dir", type=click.Path(), default="spawns", show_default=True)
@click.option("--reset", is_flag=True, help="清空该分身已学到的进化规则并移除 SKILL.md 注入。")
@click.option("--consolidate", is_flag=True, help="剪除失效（衰减）规则并刷新 SKILL.md。")
def evolve(name: str, spawns_dir: str, reset: bool, consolidate: bool) -> None:
    """运行 Tier-1 指令进化并查看进化记录（--reset 清空 / --consolidate 整理）。"""
    manager = SpawnManager(Path(spawns_dir))
    spawn_path = manager.get_spawn_path(name)

    if spawn_path is None:
        console.print(f"[red]找不到分身 '[bold]{name}[/bold]'。[/red]")
        sys.exit(1)

    if reset:
        reset_evolution(spawn_path)
        console.print(f"[green]已重置分身 '{name}' 的进化规则。[/green]")
        return

    if consolidate:
        removed = consolidate_evolution(spawn_path)
        console.print(f"[green]已整理 '{name}'：剪除 {removed} 条失效规则。[/green]")
        return

    apply_tier1_evolution(spawn_path)

    evolution_dir = spawn_path / ".evolution"
    engine = EvolutionEngine(evolution_dir)

    feedback_count = engine.feedback_store.count()
    active_rules = engine.get_active_rules()

    console.print(f"\n[bold cyan]🧬 分身 '{name}' 的进化记录[/bold cyan]\n")
    console.print(f"  累计反馈次数: [bold]{feedback_count}[/bold]")
    console.print(f"  活跃进化规则: [bold]{len(active_rules)}[/bold]\n")

    if active_rules:
        table = Table(title="活跃规则", show_header=True, header_style="bold magenta")
        table.add_column("类型", style="cyan")
        table.add_column("规则内容")
        table.add_column("置信度")
        table.add_column("样本量")

        for rule in active_rules:
            table.add_row(
                rule.rule_type,
                rule.rule,
                f"{rule.confidence:.0%}",
                str(rule.sample_size),
            )

        console.print(table)
    else:
        if feedback_count == 0:
            console.print(
                "[dim]尚无反馈记录。使用分身并提供反馈后，进化引擎将自动学习。[/dim]"
            )
        else:
            console.print(
                f"[dim]已收集 {feedback_count} 条反馈，"
                "但尚未达到生成进化规则所需的最低样本量（20条）。[/dim]"
            )
