import typer
import asyncio
from typing import Optional
from .client import CustomGPTs
from .browser import BrowserManager, DEFAULT_PROFILE_DIR
from .config import load_config, save_config, resolve_gpt
from loguru import logger
import sys

# Disable logger by default for CLI unless requested
logger.remove()

# Fix Windows console encoding for emoji/unicode
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

app = typer.Typer(help="CustomGPTs: A stealth ChatGPT web scraper.")

@app.command()
def login(
    profile: Optional[str] = typer.Option(None, "--profile", help="Path to a custom profile directory")
):
    """
    Opens ChatGPT in a visible browser window so you can log in manually.
    The profile is saved to ~/.customgpts/profile/ by default.
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
    """
    Sends a prompt to ChatGPT and prints the response.
    Uses the default GPT if --gpt is not specified and a default is set.
    """
    if verbose:
        logger.add(sys.stderr, level="INFO")

    # Resolve nickname/default
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
    """
    Start an interactive chat session. Messages stay in the same conversation.
    Type 'exit' or 'quit' to end the session.
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
    """
    List all available GPTs from your ChatGPT account.
    """
    if verbose:
        logger.add(sys.stderr, level="INFO")

    async def _gpts():
        async with CustomGPTs(visible=visible) as client:
            gpt_list = await client.list_gpts()

        config = load_config()
        saved = config.get("gpts", {})
        default = config.get("default_gpt")

        # Reverse map: id -> nickname
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
    """
    Search the GPT Store for any public custom GPT.
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
    """
    Save a GPT with a nickname for quick access.
    """
    config = load_config()
    gpts = config.get("gpts", {})

    # If target is a number, tell user to use the ID
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
    """
    Remove a saved GPT nickname.
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
    """
    Set the default GPT used when --gpt is not specified.
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
    """
    Start an OpenAI-compatible API server.
    Use with any OpenAI client library or curl.
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
