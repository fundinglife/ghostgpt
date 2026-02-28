import sys
import asyncio
from pathlib import Path
from patchright.async_api import async_playwright, BrowserContext
from loguru import logger

if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes

DEFAULT_PROFILE_DIR = Path.home() / ".customgpts" / "profile"


def _get_chrome_window_handles() -> set:
    """Get handles of all visible Chrome/Chromium windows (Win32 only)."""
    if sys.platform != "win32":
        return set()

    user32 = ctypes.windll.user32
    handles = set()

    WNDENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
    )

    def callback(hwnd, _lparam):
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
    """Get the process ID that owns a window handle."""
    pid = ctypes.wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _hide_windows(handles: set) -> int:
    """Hide windows and remove from taskbar via Win32 API."""
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
    def __init__(self, profile_dir: Path = None, headless: bool = True, visible: bool = False):
        self.profile_dir = profile_dir or DEFAULT_PROFILE_DIR
        self.headless = headless
        self.visible = visible
        self._patchright = None
        self._browser_context: BrowserContext = None
        self._watcher_task = None

        # Ensure profile directory exists
        self.profile_dir.mkdir(parents=True, exist_ok=True)

    async def start(self) -> BrowserContext:
        """Launches Chromium with a persistent context."""
        logger.info(f"Launching browser with profile: {self.profile_dir} (headless={self.headless})")

        args = ["--disable-blink-features=AutomationControlled"]

        if not self.headless and not self.visible:
            # Hidden mode: off-screen initially, then Win32 SW_HIDE on Windows
            args.append("--window-size=1280,720")
            args.append("--window-position=-3000,-3000")
        elif self.visible:
            # Visible mode: override any saved off-screen position from hidden runs
            args.append("--window-position=100,100")

        # Snapshot existing Chrome windows before launch (for Win32 hiding)
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

        # Win32: hide the browser window at OS level (browser doesn't know)
        if sys.platform == "win32" and not self.headless and not self.visible:
            for _ in range(100):  # poll up to 10s for window to appear
                await asyncio.sleep(0.1)
                new_windows = _get_chrome_window_handles() - pre_launch
                if new_windows:
                    count = _hide_windows(new_windows)
                    logger.info(f"Hidden {count} browser window(s) via Win32 ShowWindow")
                    break

            # Track patchright's PIDs so the watcher only hides OUR windows,
            # not the user's regular Chrome
            self._patchright_pids = {_get_pid_from_hwnd(h) for h in new_windows} if new_windows else set()
            logger.info(f"Patchright browser PIDs: {self._patchright_pids}")
            self._watcher_task = asyncio.create_task(self._window_watcher())

        return self._browser_context

    async def _window_watcher(self):
        """Background task that hides new patchright windows (not user's Chrome)."""
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
        """Stops the browser and patchright."""
        if self._watcher_task:
            self._watcher_task.cancel()
        if self._browser_context:
            await self._browser_context.close()
        if self._patchright:
            await self._patchright.stop()
        logger.info("Browser stopped.")

    @property
    def context(self) -> BrowserContext:
        return self._browser_context
