import typer
import asyncio
from typing import Optional
from .client import GhostGPT
from .browser import BrowserManager, DEFAULT_PROFILE_DIR
from loguru import logger
import sys

# Disable logger by default for CLI unless requested
logger.remove()

app = typer.Typer(help="GhostGPT: A stealth ChatGPT web scraper.")

@app.command()
def login(
    profile: Optional[str] = typer.Option(None, "--profile", help="Path to a custom profile directory")
):
    """
    Opens ChatGPT in a visible browser window so you can log in manually.
    The profile is saved to ~/.ghostgpt/profile/ by default.
    """
    async def _login():
        profile_path = profile if profile else DEFAULT_PROFILE_DIR
        manager = BrowserManager(profile_dir=profile_path, headless=False)
        context = await manager.start()
        page = await context.new_page()
        
        print(f"Opening ChatGPT with profile at: {profile_path}")
        await page.goto("https://chatgpt.com")
        print("\n[IMPORTANT] Please log in to ChatGPT manually in the browser window.")
        print("Once you are logged in and see the chat interface, close the browser window to save the session.\n")
        
        # Wait until the browser is closed manually
        try:
            # We wait for the context to be closed by the user closing the browser
            # or we can wait for a sentinel
            while True:
                if not context.pages:
                    break
                await asyncio.sleep(1)
        except Exception:
            pass
        finally:
            await manager.stop()
            print("Session saved. You can now use 'ghostgpt ask'.")

    asyncio.run(_login())

@app.command()
def ask(
    prompt: str,
    gpt: Optional[str] = typer.Option(None, "--gpt", help="Custom GPT ID (e.g. g-XXXXX)"),
    headless: bool = typer.Option(True, "--headless/--no-headless", help="Run with a visible browser when --no-headless"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show debug logs")
):
    """
    Sends a prompt to ChatGPT and prints the response.
    """
    if verbose:
        logger.add(sys.stderr, level="INFO")

    async def _ask():
        async with GhostGPT(headless=headless) as client:
            answer = await client.ask(prompt, gpt_id=gpt)
            # Print the raw answer
            print("\n" + "="*40)
            print(answer)
            print("="*40 + "\n")


    asyncio.run(_ask())

if __name__ == "__main__":
    app()
