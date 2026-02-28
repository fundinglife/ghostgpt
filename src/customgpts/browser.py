"""
Browser lifecycle management for CustomGPTs.

Handles launching a persistent Chromium instance via patchright (stealth Playwright fork),
managing the browser context with a reusable profile directory, and hiding the browser
window on Windows via Win32 API calls.

On Windows:
  - The browser is launched off-screen (--window-position=-3000,-3000) then hidden
    via ShowWindow(SW_HIDE) and WS_EX_TOOLWINDOW to remove it from the taskbar and
    Alt+Tab list.
  - A background watcher task re-hides any new windows (e.g., popups, devtools) that
    belong to the patchright process, identified by PID matching.

On Linux/Docker:
  - The browser renders on an Xvfb virtual display (:99). No window hiding is needed
    since there is no physical desktop. VNC access is provided via x11vnc + noVNC for
    manual login and debugging.

Usage:
    manager = BrowserManager(headless=False, visible=False)
    context = await manager.start()
    # ... use context for pages ...
    await manager.stop()
"""

import sys
import asyncio
from pathlib import Path
from patchright.async_api import async_playwright, BrowserContext
from loguru import logger

if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes

# Default persistent profile directory — stores cookies, localStorage, and session data.
# Reused across launches so the user only needs to log in to ChatGPT once.
DEFAULT_PROFILE_DIR = Path.home() / ".customgpts" / "profile"


def _get_chrome_window_handles() -> set:
    """Enumerate all visible Chrome/Chromium window handles on the current desktop.

    Uses Win32 EnumWindows to iterate over all top-level windows and filters for
    those with the Chromium window class name "Chrome_WidgetWin_1".

    Args:
        None

    Returns:
        set: A set of HWND (window handle) integers for visible Chromium windows.
             Returns an empty set on non-Windows platforms.
    """
    if sys.platform != "win32":
        return set()

    user32 = ctypes.windll.user32
    handles = set()

    WNDENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
    )

    def callback(hwnd, _lparam):
        """Win32 callback invoked for each top-level window during enumeration."""
        if not user32.IsWindowVisible(hwnd):
            return True
        class_name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_name, 256)
        if class_name.value == "Chrome_WidgetWin_1":
            handles.add(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return handles


def _get_pid_from_hwnd(hwnd) -> int:
    """Get the process ID (PID) that owns a given window handle.

    Args:
        hwnd: A Win32 HWND (window handle) integer.

    Returns:
        int: The PID of the process that created the window.
    """
    pid = ctypes.wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _hide_windows(handles: set) -> int:
    """Hide browser windows and remove them from the Windows taskbar.

    For each window handle, this function:
      1. Strips the WS_EX_APPWINDOW extended style (removes from taskbar).
      2. Adds the WS_EX_TOOLWINDOW extended style (hides from Alt+Tab).
      3. Calls ShowWindow(SW_HIDE) to make the window invisible.

    Args:
        handles: A set of HWND integers to hide.

    Returns:
        int: The number of windows successfully hidden. Returns 0 on
             non-Windows platforms or if the handles set is empty.
    """
    if sys.platform != "win32" or not handles:
        return 0
    user32 = ctypes.windll.user32
    GWL_EXSTYLE = -20
    WS_EX_APPWINDOW = 0x00040000
    WS_EX_TOOLWINDOW = 0x00000080
    count = 0
    for hwnd in handles:
        # Remove from taskbar: strip APPWINDOW, add TOOLWINDOW
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, (style & ~WS_EX_APPWINDOW) | WS_EX_TOOLWINDOW)
        user32.ShowWindow(hwnd, 0)  # SW_HIDE
        count += 1
    return count


class BrowserManager:
    """Manages the lifecycle of a persistent Chromium browser instance.

    Launches Chromium via patchright with stealth flags to bypass anti-bot detection.
    The browser uses a persistent profile directory so login sessions survive restarts.

    Attributes:
        profile_dir (Path): Directory for the persistent Chromium user profile.
        headless (bool): If True, run Chromium in headless mode (no GUI).
        visible (bool): If True, show the browser window to the user. If False and
                        not headless, the window is hidden via OS-level APIs.

    Example:
        manager = BrowserManager(headless=False, visible=False)
        context = await manager.start()
        page = await context.new_page()
        await page.goto("https://chatgpt.com")
        await manager.stop()
    """

    def __init__(self, profile_dir: Path = None, headless: bool = True, visible: bool = False):
        """Initialize the BrowserManager.

        Args:
            profile_dir: Path to the Chromium user data directory. Defaults to
                         ~/.customgpts/profile/ if not specified.
            headless: Whether to run the browser in headless mode (no GUI at all).
            visible: Whether to show the browser window to the user. Only meaningful
                     when headless=False. When False, the browser is hidden via Win32
                     API on Windows or runs on a virtual display on Linux.
        """
        self.profile_dir = profile_dir or DEFAULT_PROFILE_DIR
        self.headless = headless
        self.visible = visible
        self._patchright = None
        self._browser_context: BrowserContext = None
        self._watcher_task = None

        # Ensure profile directory exists
        self.profile_dir.mkdir(parents=True, exist_ok=True)

    async def start(self) -> BrowserContext:
        """Launch Chromium with a persistent context and return the BrowserContext.

        The browser is launched with the stealth flag --disable-blink-features=AutomationControlled
        to avoid detection by ChatGPT's anti-bot systems.

        On Windows in hidden mode:
          - Takes a snapshot of existing Chrome windows before launch.
          - After launch, polls for new windows (up to 10s) and hides them via Win32 API.
          - Records patchright's PIDs and starts a background watcher to hide any future
            windows (popups, devtools) from the same process.

        Returns:
            BrowserContext: The patchright persistent browser context, ready for page creation.

        Raises:
            Exception: If the browser fails to launch (e.g., missing Chromium installation).
        """
        logger.info(f"Launching browser with profile: {self.profile_dir} (headless={self.headless})")

        args = ["--disable-blink-features=AutomationControlled"]

        if not self.headless and not self.visible:
            # Hidden mode: size the window, position off-screen on Windows only.
            # On Linux/Docker, the browser renders on Xvfb virtual display.
            args.append("--window-size=1280,720")
            if sys.platform == "win32":
                args.append("--window-position=-3000,-3000")
        elif self.visible:
            # Visible mode: override any saved off-screen position from previous hidden runs
            args.append("--window-position=100,100")

        # Snapshot existing Chrome windows before launch so we only hide NEW ones
        pre_launch = set()
        if sys.platform == "win32" and not self.headless and not self.visible:
            pre_launch = _get_chrome_window_handles()

        self._patchright = await async_playwright().start()
        self._browser_context = await self._patchright.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            headless=self.headless,
            args=args,
            no_viewport=True,
        )

        # Win32: hide the browser window at OS level (browser doesn't know it's hidden)
        if sys.platform == "win32" and not self.headless and not self.visible:
            for _ in range(100):  # poll up to 10s for window to appear
                await asyncio.sleep(0.1)
                new_windows = _get_chrome_window_handles() - pre_launch
                if new_windows:
                    count = _hide_windows(new_windows)
                    logger.info(f"Hidden {count} browser window(s) via Win32 ShowWindow")
                    break

            # Track patchright's PIDs so the background watcher only hides OUR windows,
            # not the user's regular Chrome browser
            self._patchright_pids = {_get_pid_from_hwnd(h) for h in new_windows} if new_windows else set()
            logger.info(f"Patchright browser PIDs: {self._patchright_pids}")
            self._watcher_task = asyncio.create_task(self._window_watcher())

        return self._browser_context

    async def _window_watcher(self):
        """Background task that continuously monitors for and hides new patchright windows.

        Runs every 1 second, checking all visible Chrome windows. If a window belongs
        to a patchright PID (identified during start()), it gets hidden immediately.
        This catches popup windows, permission dialogs, and devtools that Chrome may
        open after the initial launch.

        This task runs until cancelled by stop().
        """
        while True:
            try:
                await asyncio.sleep(1)
                for hwnd in _get_chrome_window_handles():
                    pid = _get_pid_from_hwnd(hwnd)
                    if pid in self._patchright_pids:
                        _hide_windows({hwnd})
                        logger.info(f"Watcher: hidden patchright window (PID {pid})")
            except asyncio.CancelledError:
                break
            except Exception:
                continue

    async def stop(self):
        """Stop the browser and clean up all resources.

        Cancels the window watcher task (if running), closes the browser context,
        and stops the patchright Playwright instance.
        """
        if self._watcher_task:
            self._watcher_task.cancel()
        if self._browser_context:
            await self._browser_context.close()
        if self._patchright:
            await self._patchright.stop()
        logger.info("Browser stopped.")

    @property
    def context(self) -> BrowserContext:
        """The active patchright BrowserContext, or None if not yet started.

        Returns:
            BrowserContext: The persistent browser context for creating pages.
        """
        return self._browser_context
