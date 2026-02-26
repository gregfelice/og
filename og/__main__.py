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


@click.command()
@click.argument("message", required=False)
@click.option("--session", "-s", default=None, help="Session name (default: auto)")
@click.option("--model", "-m", default=None, help="Model override")
def main(message: str | None, session: str | None, model: str | None) -> None:
    """OG — OpenClaw Python PoC agent."""
    load_dotenv()
    config = Config()

    if model:
        config.llm.model = model

    session_id = session or config.session.default_session
    asyncio.run(_run(config, message, session_id))


if __name__ == "__main__":
    main()
