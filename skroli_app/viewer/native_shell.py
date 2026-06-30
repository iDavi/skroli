"""Optional cross-platform native shell (extra: ``skroli[native]``).

Wraps the skroli web UI in a real native window with browser-style tabs on
Windows / macOS / Linux using PySide6 + QtWebEngine.

The window is **frameless** and we own the whole top row: window buttons, the
tab bar, and the new-tab button all live there, Chrome-style. We deliberately do
*not* touch the native title bar (the transparent / full-size-content tricks
macOS keeps resetting on zoom, which made the window undraggable and flashed a
black bar). Instead:

  * dragging uses Qt's native ``startSystemMove`` (rock-solid on every OS);
  * window buttons are drawn by us — on macOS as traffic-light circles
    (top-left), elsewhere as minimize/maximize/close (top-right);
  * on macOS we add only the *resizable* style-mask bit (a one-time, harmless
    AppKit touch) so a borderless window can still be edge-resized.

The feed / config UI is the same web app loaded with ``?shell=1`` (it hides its
own web tab strip); posts/comments open as full Chromium tabs via
``createWindow``. Import is lazy and guarded by the caller.
"""

from __future__ import annotations

# Qt stylesheet from the web UI's design tokens (olive / parchment / gold) so
# the native chrome reads as skroli, not default dark Qt.
_QSS = """
QMainWindow, QWidget { background: #4f4b3b; color: #f5f3ec; }
#topbar, #dragbar, #maclights, #wincontrols { background: #4f4b3b; }

QTabBar#tabbar { background: #4f4b3b; }
QTabBar#tabbar::tab {
  background: #4f4b3b; color: #d9d6c8;
  height: 44px; min-width: 120px; max-width: 220px; padding: 0 8px 0 14px;
  border: 0; border-right: 1px solid #605b46;
  font-family: "Libertinus Math", "Libertinus Serif", Georgia, serif;
  font-size: 14px;
}
QTabBar#tabbar::tab:hover { background: #56523f; }
QTabBar#tabbar::tab:selected {
  background: #56523f; color: #f5f3ec; border-bottom: 2px solid #c9b27a;
}
QTabBar#tabbar::close-button { subcontrol-position: right; margin: 0 6px 0 4px; }

QToolButton#plus {
  background: transparent; color: #959389; border: 0;
  font-size: 20px; padding: 4px 14px;
}
QToolButton#plus:hover { background: #56523f; color: #f5f3ec; }

/* macOS traffic-light buttons (we draw them; frameless removes the real ones) */
#macclose, #macmin, #maczoom {
  border: 0; min-width: 12px; max-width: 12px; min-height: 12px; max-height: 12px;
  border-radius: 6px;
}
#macclose { background: #ff5f57; }
#macmin   { background: #febc2e; }
#maczoom  { background: #28c840; }

/* Windows / Linux window buttons */
#winmin, #winmax, #winclose {
  background: transparent; color: #d9d6c8; border: 0;
  min-width: 46px; min-height: 44px; font-size: 14px;
}
#winmin:hover, #winmax:hover { background: #56523f; }
#winclose:hover { background: #c0392b; color: #fff; }
"""


def run(url: str) -> None:
    """Open the native shell pointed at the local server ``url`` and block until
    closed. Raises ImportError if PySide6 isn't installed."""
    import sys

    from PySide6.QtCore import QEvent, QUrl, Qt
    from PySide6.QtGui import QKeySequence, QShortcut
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import (
        QApplication,
        QHBoxLayout,
        QMainWindow,
        QPushButton,
        QStackedWidget,
        QTabBar,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )

    is_mac = sys.platform == "darwin"
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(_QSS)
    profile = QWebEngineProfile("skroli", app)   # shared cookies/cache/logins

    class DragBar(QWidget):
        """The empty stretch of the top row; dragging it moves the window,
        double-click maximizes. Uses a manual cursor-delta move (startSystemMove
        proved unreliable for this frameless window), with a native fallback."""

        def __init__(self, shell):
            super().__init__()
            self.setObjectName("dragbar")
            self._shell = shell
            self._press = None       # global cursor pos when the drag started
            self._origin = None      # window top-left when the drag started

        def mousePressEvent(self, event):  # noqa: N802 (Qt naming)
            if event.button() == Qt.MouseButton.LeftButton:
                self._press = event.globalPosition().toPoint()
                self._origin = self._shell.frameGeometry().topLeft()
                event.accept()

        def mouseMoveEvent(self, event):  # noqa: N802
            if self._press is not None:
                delta = event.globalPosition().toPoint() - self._press
                self._shell.move(self._origin + delta)
                event.accept()

        def mouseReleaseEvent(self, event):  # noqa: N802
            self._press = None
            self._origin = None

        def mouseDoubleClickEvent(self, event):  # noqa: N802
            self._shell.toggle_max()

    class ShellPage(QWebEnginePage):
        """Routes window.open / target=_blank / modified clicks to a new tab."""

        def __init__(self, shell):
            super().__init__(profile, shell)
            self._shell = shell

        def createWindow(self, win_type):  # noqa: N802
            background = win_type == QWebEnginePage.WebWindowType.WebBrowserBackgroundTab
            return self._shell.add_tab(focus=not background).page()

    class Shell(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("skroli")
            self.resize(1200, 900)
            self.setMinimumSize(640, 480)
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)

            # --- tab bar (standalone, paired with a stacked content area) ---
            self.tabbar = QTabBar()
            self.tabbar.setObjectName("tabbar")
            self.tabbar.setTabsClosable(True)
            self.tabbar.setMovable(True)
            self.tabbar.setExpanding(False)
            self.tabbar.setDrawBase(False)
            self.tabbar.setElideMode(Qt.TextElideMode.ElideRight)
            self.tabbar.currentChanged.connect(self._on_current)
            self.tabbar.tabCloseRequested.connect(self.close_tab)
            self.tabbar.tabMoved.connect(self._on_moved)
            self.tabbar.installEventFilter(self)   # middle-click closes a tab

            self.stack = QStackedWidget()

            plus = QToolButton()
            plus.setObjectName("plus")
            plus.setText("+")
            plus.setToolTip("New feed tab")
            plus.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            plus.clicked.connect(lambda: self.new_home_tab(focus=True))

            # --- top row: [buttons?] tabs + add + draggable filler [buttons?] ---
            top = QWidget()
            top.setObjectName("topbar")
            row = QHBoxLayout(top)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(0)
            if is_mac:
                row.addWidget(self._mac_lights())
            row.addWidget(self.tabbar)
            row.addWidget(plus)
            row.addWidget(DragBar(self), 1)
            if not is_mac:
                row.addWidget(self._win_controls())

            central = QWidget()
            col = QVBoxLayout(central)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(0)
            col.addWidget(top)
            col.addWidget(self.stack, 1)
            self.setCentralWidget(central)

            self._wire_shortcuts()
            self.new_home_tab(focus=True)

        # ---- window buttons -----------------------------------------------
        def _btn(self, obj_name, tip, slot, text=""):
            b = QPushButton(text)
            b.setObjectName(obj_name)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(slot)
            return b

        def _mac_lights(self):
            w = QWidget()
            w.setObjectName("maclights")
            lay = QHBoxLayout(w)
            lay.setContentsMargins(13, 0, 10, 0)
            lay.setSpacing(8)
            lay.addWidget(self._btn("macclose", "Close", self.close))
            lay.addWidget(self._btn("macmin", "Minimize", self.showMinimized))
            lay.addWidget(self._btn("maczoom", "Zoom", self.toggle_max))
            return w

        def _win_controls(self):
            w = QWidget()
            w.setObjectName("wincontrols")
            lay = QHBoxLayout(w)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(0)
            lay.addWidget(self._btn("winmin", "Minimize", self.showMinimized, "—"))
            lay.addWidget(self._btn("winmax", "Maximize", self.toggle_max, "☐"))
            lay.addWidget(self._btn("winclose", "Close", self.close, "✕"))
            return w

        def toggle_max(self):
            self.showNormal() if self.isMaximized() else self.showMaximized()

        # ---- tabs ----------------------------------------------------------
        def _new_view(self) -> QWebEngineView:
            view = QWebEngineView()
            view.setPage(ShellPage(self))
            view.titleChanged.connect(lambda t, v=view: self._set_title(v, t))
            view.iconChanged.connect(lambda i, v=view: self._set_icon(v, i))
            return view

        def add_tab(self, focus: bool = True) -> QWebEngineView:
            view = self._new_view()
            idx = self.stack.addWidget(view)
            self.tabbar.addTab("Loading…")
            if focus:
                self.tabbar.setCurrentIndex(idx)
            return view

        def new_home_tab(self, focus: bool = False) -> QWebEngineView:
            view = self._new_view()
            idx = self.stack.addWidget(view)
            self.tabbar.addTab("Feed")
            view.load(QUrl(url + "/?shell=1"))
            if focus:
                self.tabbar.setCurrentIndex(idx)
            return view

        def close_tab(self, index: int) -> None:
            view = self.stack.widget(index)
            self.tabbar.removeTab(index)
            if view is not None:
                self.stack.removeWidget(view)
                view.deleteLater()
            if self.tabbar.count() == 0:
                self.new_home_tab(focus=True)

        def close_current(self) -> None:
            self.close_tab(self.tabbar.currentIndex())

        def _on_current(self, index: int) -> None:
            if index >= 0:
                self.stack.setCurrentIndex(index)
            view = self.stack.currentWidget()
            if view is not None:
                self.setWindowTitle((view.title() or "skroli").strip() or "skroli")

        def _on_moved(self, frm: int, to: int) -> None:
            widget = self.stack.widget(frm)
            self.stack.removeWidget(widget)
            self.stack.insertWidget(to, widget)
            self.stack.setCurrentIndex(self.tabbar.currentIndex())

        def _set_title(self, view, title: str) -> None:
            idx = self.stack.indexOf(view)
            if idx >= 0:
                self.tabbar.setTabText(idx, (title or "").strip() or "Untitled")
            if view is self.stack.currentWidget():
                self.setWindowTitle((title or "").strip() or "skroli")

        def _set_icon(self, view, icon) -> None:
            idx = self.stack.indexOf(view)
            if idx >= 0:
                self.tabbar.setTabIcon(idx, icon)

        # ---- input ---------------------------------------------------------
        def _wire_shortcuts(self) -> None:
            QShortcut(QKeySequence.StandardKey.AddTab, self,
                      activated=lambda: self.new_home_tab(focus=True))
            QShortcut(QKeySequence("Ctrl+W"), self, activated=self.close_current)
            QShortcut(QKeySequence.StandardKey.Close, self, activated=self.close_current)
            QShortcut(QKeySequence("Ctrl+Tab"), self, activated=lambda: self._cycle(1))
            QShortcut(QKeySequence("Ctrl+Shift+Tab"), self, activated=lambda: self._cycle(-1))

        def _cycle(self, delta: int) -> None:
            n = self.tabbar.count()
            if n:
                self.tabbar.setCurrentIndex((self.tabbar.currentIndex() + delta) % n)

        def eventFilter(self, obj, event):  # noqa: N802
            if (obj is self.tabbar
                    and event.type() == QEvent.Type.MouseButtonRelease
                    and event.button() == Qt.MouseButton.MiddleButton):
                i = self.tabbar.tabAt(event.position().toPoint())
                if i >= 0:
                    self.close_tab(i)
                    return True
            return super().eventFilter(obj, event)

        # ---- macOS: keep a borderless window edge-resizable -----------------
        def enable_macos_resize(self) -> None:
            if not is_mac:
                return
            try:
                from ctypes import c_void_p

                import objc
                from AppKit import NSWindowStyleMaskResizable

                view = objc.objc_object(c_void_p=int(self.winId()))
                nswindow = view.window()
                nswindow.setStyleMask_(nswindow.styleMask() | NSWindowStyleMaskResizable)
            except Exception:  # noqa: BLE001 - resize is a nicety, never crash
                pass

    window = Shell()
    window.show()
    window.enable_macos_resize()   # after show(): the NSWindow exists
    app.exec()
