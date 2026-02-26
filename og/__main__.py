"""CLI entry point for OG."""

from __future__ import annotations

import asyncio

import click
from dotenv import load_dotenv
from rich.console import Console

from og.channels.cli import CLIChannel
from og.config.schema import Config
from og.core.agent import Agent
from og.core.budget import BudgetExceeded


async def interactive_loop(agent: Agent, channel: CLIChannel, session_id: str) -> None:
    """Main interactive REPL loop."""
    channel.print_welcome(session_id)

    while True:
        message = await channel.receive()
        if message is None:
            channel.console.print(f"\n[dim]Goodbye. {agent.budget.summary()}[/dim]")
            break
        if not message:
            continue

        await channel.show_status("Thinking...")

        try:
            async for chunk in agent.run_stream(message, session_id):
                await channel.stream(chunk)
            await channel.stream_end()
            channel.console.print(f"  [dim]{agent.budget.summary()}[/dim]")
        except BudgetExceeded as e:
            await channel.send(f"**Budget limit reached:** {e}")
            break
        except Exception as e:
            await channel.send(f"**Error:** {e}")


async def one_shot(agent: Agent, message: str, session_id: str) -> None:
    """Single message mode — print response and exit."""
    from rich.markdown import Markdown

    console = Console()
    try:
        response = await agent.run(message, session_id)
        console.print(Markdown(response))
        console.print(f"\n[dim]{agent.budget.summary()}[/dim]")
    except BudgetExceeded as e:
        console.print(f"[bold red]Budget limit reached:[/bold red] {e}")


async def _run(config: Config, message: str | None, session_id: str) -> None:
    """Async entry: create agent then dispatch to one-shot or interactive."""
    agent = await Agent.create(config)
    try:
        if message:
            await one_shot(agent, message, session_id)
        else:
            channel = CLIChannel()
            await interactive_loop(agent, channel, session_id)
    finally:
        if agent.pool is not None:
            await agent.pool.close()


class DefaultGroup(click.Group):
    """Falls through to 'chat' when no subcommand matches."""

    def parse_args(self, ctx, args):
        # Let --help and --version through to the group itself
        if not args:
            args = ["chat"]
        elif args[0] not in self.commands and not args[0].startswith("-"):
            # Bare message arg — route to chat
            args = ["chat"] + args
        elif args[0] not in self.commands and args[0] in ("-s", "--session", "-m", "--model"):
            # Chat options without explicit subcommand
            args = ["chat"] + args
        return super().parse_args(ctx, args)


@click.group(cls=DefaultGroup)
def main():
    """OG — OpenClaw Python PoC agent."""


@main.command()
@click.argument("message", required=False)
@click.option("--session", "-s", default=None, help="Session name (default: auto)")
@click.option("--model", "-m", default=None, help="Model override")
def chat(message: str | None, session: str | None, model: str | None) -> None:
    """Start interactive chat or send a one-shot message."""
    load_dotenv()
    config = Config()

    if model:
        config.llm.model = model

    session_id = session or config.session.default_session
    asyncio.run(_run(config, message, session_id))


@main.command()
@click.argument("query")
@click.option("--project", "-p", default=None, help="Project ID override")
@click.option("--entity", "-e", multiple=True, help="Entities for graph-boosted search")
@click.option("--limit", "-n", default=10, help="Max results")
def recall(query: str, project: str | None, entity: tuple[str, ...], limit: int) -> None:
    """Search stored knowledge for relevant context."""
    from og.cli.hooks import recall_impl

    entities = list(entity) if entity else None
    result = asyncio.run(
        recall_impl(query, project_id=project or "", entities=entities, limit=limit)
    )
    if result:
        click.echo(result)


@main.command()
@click.option("--file", "transcript_file", required=True, help="Path to JSONL transcript")
@click.option("--session-id", default=None, help="Session ID for the transcript")
@click.option("--project", "-p", default=None, help="Project ID override")
def extract(transcript_file: str, session_id: str | None, project: str | None) -> None:
    """Extract knowledge from a Claude Code transcript."""
    from og.cli.hooks import extract_impl

    result = asyncio.run(extract_impl(transcript_file, session_id=session_id, project_id=project))
    click.echo(result)


@main.command()
@click.option("--project", "-p", default=None, help="Project ID override")
@click.option("--limit", "-n", default=20, help="Max chunks to inject")
def inject(project: str | None, limit: int) -> None:
    """Inject stored context (decisions, constraints, patterns, corrections)."""
    from og.cli.hooks import inject_impl

    result = asyncio.run(inject_impl(project_id=project, limit=limit))
    if result:
        click.echo(result)


if __name__ == "__main__":
    main()
