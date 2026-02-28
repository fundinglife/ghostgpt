"""
Typer CLI application for CustomGPTs.

Provides all command-line commands for interacting with ChatGPT via the browser
scraper. Each command is a thin wrapper around the async Python API (client.py),
bridged to synchronous execution via asyncio.run().

Commands:
    login    — Open a visible browser for manual ChatGPT login
    ask      — Send a single prompt and print the response
    chat     — Start an interactive multi-turn chat session
    serve    — Start the OpenAI-compatible API server
    gpts     — List available GPTs from the user's account
    search   — Search the GPT Store for public GPTs
    star     — Save a GPT with a nickname for quick access
    unstar   — Remove a saved GPT nickname
    default  — Set or clear the default GPT

Usage:
    customgpts login
    customgpts ask "What is the capital of France?"
    customgpts ask "Explain gravity" --gpt teacher
    customgpts chat --visible
    customgpts serve --port 5124 --verbose
"""

import typer
import asyncio
from typing import Optional
from .client import CustomGPTs
from .browser import BrowserManager, DEFAULT_PROFILE_DIR
from .config import load_config, save_config, resolve_gpt
from loguru import logger
import sys

# Disable loguru output by default for clean CLI output.
# Re-enabled per-command with --verbose flag.
logger.remove()

# Fix Windows console encoding for emoji/unicode characters in ChatGPT responses
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

app = typer.Typer(help="CustomGPTs: A stealth ChatGPT web scraper.")


@app.command()
def login(
    profile: Optional[str] = typer.Option(None, "--profile", help="Path to a custom profile directory")
):
    """Open ChatGPT in a visible browser window for manual login.

    Launches Chromium with the persistent profile directory and navigates to ChatGPT.
    The user logs in manually in the browser window. When they close the window,
    the session is saved to disk and reused by all subsequent commands.

    Args:
        profile: Optional custom path for the browser profile directory.
                 Defaults to ~/.customgpts/profile/.
    """
    async def _login():
        profile_path = profile if profile else DEFAULT_PROFILE_DIR
        manager = BrowserManager(profile_dir=profile_path, headless=False, visible=True)
        context = await manager.start()
        page = await context.new_page()

        print(f"Opening ChatGPT with profile at: {profile_path}")
        await page.goto("https://chatgpt.com")
        print("\n[IMPORTANT] Please log in to ChatGPT manually in the browser window.")
        print("Once you are logged in and see the chat interface, close the browser window to save the session.\n")

        try:
            # Wait until the user closes all browser pages
            while True:
                if not context.pages:
                    break
                await asyncio.sleep(1)
        except Exception:
            pass
        finally:
            await manager.stop()
            print("Session saved. You can now use 'customgpts ask'.")

    asyncio.run(_login())


@app.command()
def ask(
    prompt: str,
    gpt: Optional[str] = typer.Option(None, "--gpt", help="GPT nickname or ID (e.g. 'teacher' or g-XXXXX)"),
    visible: bool = typer.Option(False, "--visible", help="Show the browser window"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show debug logs")
):
    """Send a prompt to ChatGPT and print the response.

    Uses the default GPT if --gpt is not specified and a default is set in config.

    Args:
        prompt: The message to send to ChatGPT.
        gpt: Optional GPT nickname or raw ID. If a nickname, it's resolved via config.
        visible: If True, show the browser window during interaction.
        verbose: If True, enable debug logging to stderr.
    """
    if verbose:
        logger.add(sys.stderr, level="INFO")

    # Resolve nickname to GPT ID, or use default
    gpt_id = resolve_gpt(gpt)
    if gpt and not gpt_id:
        print(f"Unknown GPT nickname: '{gpt}'. Use 'customgpts gpts' to see available GPTs.")
        raise typer.Exit(1)

    if gpt_id and verbose:
        logger.info(f"Resolved GPT: {gpt} -> {gpt_id}")

    async def _ask():
        async with CustomGPTs(visible=visible) as client:
            answer = await client.ask(prompt, gpt_id=gpt_id)
            print("\n" + "="*40)
            print(answer)
            print("="*40 + "\n")

    asyncio.run(_ask())


@app.command()
def chat(
    gpt: Optional[str] = typer.Option(None, "--gpt", help="GPT nickname or ID (e.g. 'teacher' or g-XXXXX)"),
    visible: bool = typer.Option(False, "--visible", help="Show the browser window"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show debug logs")
):
    """Start an interactive multi-turn chat session.

    Messages stay in the same conversation thread (continue_conversation=True).
    Type 'exit' or 'quit' to end the session.

    Args:
        gpt: Optional GPT nickname or raw ID to use for the session.
        visible: If True, show the browser window during the session.
        verbose: If True, enable debug logging to stderr.
    """
    if verbose:
        logger.add(sys.stderr, level="INFO")

    gpt_id = resolve_gpt(gpt)
    if gpt and not gpt_id:
        print(f"Unknown GPT nickname: '{gpt}'. Use 'customgpts gpts' to see available GPTs.")
        raise typer.Exit(1)

    label = gpt or "ChatGPT"

    async def _chat():
        async with CustomGPTs(visible=visible) as client:
            print(f"\n  Session started with {label}. Type 'exit' to end.\n")
            first = True
            while True:
                try:
                    user_input = input("You: ").strip()
                except (EOFError, KeyboardInterrupt):
                    break

                if not user_input:
                    continue
                if user_input.lower() in ("exit", "quit", "/exit", "/quit"):
                    break

                answer = await client.ask(
                    user_input,
                    gpt_id=gpt_id,
                    continue_conversation=not first,
                )
                first = False
                print(f"\nChatGPT: {answer}\n")

            print("  Session ended.\n")

    asyncio.run(_chat())


@app.command()
def gpts(
    visible: bool = typer.Option(False, "--visible", help="Show the browser window"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show debug logs")
):
    """List all available GPTs from the user's ChatGPT account.

    Fetches pinned and custom GPTs via ChatGPT's backend API, then displays them
    alongside any saved nicknames and the current default GPT from config.

    Args:
        visible: If True, show the browser window during the fetch.
        verbose: If True, enable debug logging to stderr.
    """
    if verbose:
        logger.add(sys.stderr, level="INFO")

    async def _gpts():
        async with CustomGPTs(visible=visible) as client:
            gpt_list = await client.list_gpts()

        config = load_config()
        saved = config.get("gpts", {})
        default = config.get("default_gpt")

        # Reverse map: GPT ID -> saved nickname
        id_to_nick = {v: k for k, v in saved.items()}

        print("\n  Available GPTs:\n")
        for i, g in enumerate(gpt_list, 1):
            nick = id_to_nick.get(g["id"], "")
            label = f"  [{nick}]" if nick else ""
            tag = f"({g['type']})" if g["type"] == "custom" else ""
            print(f"  {i:>3}. {g['name']:<40} {g['id']:<45} {tag}{label}")

        if saved:
            print("\n  Saved nicknames:\n")
            for nick, gid in saved.items():
                gpt_name = next((g["name"] for g in gpt_list if g["id"] == gid), "?")
                marker = " (default)" if nick == default else ""
                print(f"    {nick:<20} -> {gid} ({gpt_name}){marker}")

        if default:
            print(f"\n  Default: {default}")

        print()


    asyncio.run(_gpts())


@app.command()
def search(
    query: str = typer.Argument(help="Search keyword (e.g. 'code review', 'image generator')"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results to show"),
    visible: bool = typer.Option(False, "--visible", help="Show the browser window"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show debug logs")
):
    """Search the GPT Store for public custom GPTs by keyword.

    Displays results with GPT name, ID, description, and author. Use 'customgpts star'
    to save a result by its ID with a nickname.

    Args:
        query: The search keyword to find GPTs.
        limit: Maximum number of results to return. Defaults to 20.
        visible: If True, show the browser window during the search.
        verbose: If True, enable debug logging to stderr.
    """
    if verbose:
        logger.add(sys.stderr, level="INFO")

    async def _search():
        async with CustomGPTs(visible=visible) as client:
            results = await client.search_gpts(query, limit=limit)

        if not results:
            print(f"\n  No GPTs found for '{query}'.\n")
            return

        print(f"\n  Search results for '{query}':\n")
        for i, g in enumerate(results, 1):
            desc = g.get("description", "")
            desc_short = (desc[:60] + "...") if len(desc) > 60 else desc
            print(f"  {i:>3}. {g['name']:<35} {g['id']:<45}")
            if desc_short:
                print(f"       {desc_short}")
            print(f"       by {g.get('author', '?')}")
            print()

        print(f"  Star a result: customgpts star <ID> <nickname>")
        print()

    asyncio.run(_search())


@app.command()
def star(
    target: str = typer.Argument(help="GPT ID (e.g. g-XXXXX) to save"),
    nickname: str = typer.Argument(help="Short nickname for this GPT"),
):
    """Save a GPT with a nickname for quick access.

    Maps a short nickname to a GPT ID in the config file. The nickname can then
    be used with --gpt in other commands or as a model name in the API server.

    Args:
        target: The GPT ID to save (e.g., "g-abc123").
        nickname: A short, memorable name for this GPT (e.g., "teacher").
    """
    config = load_config()
    gpts = config.get("gpts", {})

    # Prevent common mistake of using a search result number instead of ID
    if target.isdigit():
        print(f"Use the GPT ID instead of number. Run 'customgpts gpts' to see IDs.")
        raise typer.Exit(1)

    gpts[nickname] = target
    config["gpts"] = gpts
    save_config(config)
    print(f"Saved: {nickname} -> {target}")


@app.command()
def unstar(
    nickname: str = typer.Argument(help="Nickname to remove"),
):
    """Remove a saved GPT nickname from the config.

    Also clears the default GPT if the removed nickname was the current default.

    Args:
        nickname: The nickname to remove (e.g., "teacher").
    """
    config = load_config()
    gpts = config.get("gpts", {})

    if nickname not in gpts:
        print(f"Nickname '{nickname}' not found.")
        raise typer.Exit(1)

    removed_id = gpts.pop(nickname)
    # Clear default if it was this nickname
    if config.get("default_gpt") == nickname:
        config["default_gpt"] = None

    config["gpts"] = gpts
    save_config(config)
    print(f"Removed: {nickname} (was {removed_id})")


@app.command("default")
def set_default(
    nickname: str = typer.Argument(help="Nickname to use as default (or 'none' to clear)"),
):
    """Set the default GPT used when --gpt is not specified.

    The default GPT is used automatically by 'ask', 'chat', and the API server
    when no explicit GPT is requested. Pass 'none' to clear the default.

    Args:
        nickname: The saved nickname to set as default, or "none" to clear.
    """
    config = load_config()

    if nickname.lower() == "none":
        config["default_gpt"] = None
        save_config(config)
        print("Default GPT cleared.")
        return

    gpts = config.get("gpts", {})
    if nickname not in gpts:
        print(f"Nickname '{nickname}' not found. Save it first with 'customgpts star <id> {nickname}'.")
        raise typer.Exit(1)

    config["default_gpt"] = nickname
    save_config(config)
    print(f"Default GPT set to: {nickname} ({gpts[nickname]})")


@app.command()
def serve(
    port: int = typer.Option(5124, "--port", "-p", help="Port to listen on"),
    host: str = typer.Option("0.0.0.0", "--host", help="Host to bind to"),
    visible: bool = typer.Option(False, "--visible", help="Show the browser window"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show debug logs"),
):
    """Start an OpenAI-compatible API server.

    Launches Chromium and starts a Starlette/uvicorn server that exposes ChatGPT
    via the standard OpenAI chat completions API format. Compatible with the
    OpenAI Python client library and any tool that speaks the OpenAI API.

    Endpoints:
        POST /v1/chat/completions  — Chat completion (streaming + non-streaming)
        GET  /v1/models            — List available models
        GET  /health               — Health check

    Args:
        port: The port to listen on. Defaults to 5124.
        host: The host to bind to. Defaults to "0.0.0.0" (all interfaces).
        visible: If True, show the browser window.
        verbose: If True, enable debug logging.
    """
    if verbose:
        logger.add(sys.stderr, level="INFO")

    from .server import app as server_app, configure
    import uvicorn

    configure(visible=visible)
    print(f"\n  CustomGPTs API server starting on http://{host}:{port}")
    print(f"  OpenAI endpoint: http://{host}:{port}/v1/chat/completions")
    print(f"  Health check:    http://{host}:{port}/health\n")
    uvicorn.run(server_app, host=host, port=port, log_level="info" if verbose else "warning")


if __name__ == "__main__":
    app()
