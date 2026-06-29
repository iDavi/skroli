"""Optional cross-platform native shell (extra: ``skroli[native]``).

Wraps the skroli web UI in a real native window with native, draggable,
closable tabs on Windows / macOS / Linux using PySide6 + QtWebEngine — the OS
draws the window frame and its real min/maximize/close buttons, and the tab bar
is a native ``QTabBar`` that sits in its own row (browser-style) without any of
the title-bar hacks pywebview needed.

The feed / config UI is the *same* web app, loaded with ``?shell=1`` so it hides
its own (web) tab strip and lets the native tabs drive navigation. Article and
comment pages open as full Chromium tabs, so there's no need for the
X-Frame-Options proxy here — each tab is a real top-level browser view.

Import is lazy and guarded by the caller: if PySide6 isn't installed, the viewer
falls back to pywebview, then to a plain browser tab.
"""

from __future__ import annotations


def run(url: str) -> None:
    """Open the native shell pointed at the local server ``url`` and block until
    the window is closed. Raises ImportError if PySide6 isn't available."""
    import sys

    from PySide6.QtCore import QUrl, Qt
    from PySide6.QtGui import QKeySequence, QShortcut
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget, QToolButton

    app = QApplication.instance() or QApplication(sys.argv)
    # One shared profile so cookies/cache/logins persist across tabs.
    profile = QWebEngineProfile("skroli", app)

    class ShellPage(QWebEnginePage):
        """A page that routes window.open / target=_blank / modified clicks to a
        new native tab instead of a popup window."""

        def __init__(self, shell):
            super().__init__(profile, shell)
            self._shell = shell

        def createWindow(self, win_type):  # noqa: N802 (Qt naming)
            background = win_type == QWebEnginePage.WebWindowType.WebBrowserBackgroundTab
            return self._shell.add_tab(focus=not background).page()

    class Shell(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("skroli")
            self.resize(1200, 900)

            self.tabs = QTabWidget()
            self.tabs.setTabsClosable(True)   # native × on each tab
            self.tabs.setMovable(True)        # native drag-reorder
            self.tabs.setDocumentMode(True)   # browser-like flat tabs
            self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
            self.tabs.tabCloseRequested.connect(self.close_tab)
            self.tabs.currentChanged.connect(self._on_current_changed)
            self.setCentralWidget(self.tabs)

            plus = QToolButton()
            plus.setText("+")
            plus.setToolTip("New feed tab")
            plus.clicked.connect(lambda: self.new_home_tab(focus=True))
            self.tabs.setCornerWidget(plus, Qt.Corner.TopRightCorner)

            # Middle-click a tab to close it (browser convention).
            self.tabs.tabBar().setChangeCurrentOnDrag(True)
            self.tabs.tabBar().installEventFilter(self)

            self._wire_shortcuts()
            self.new_home_tab(focus=True)

        # ---- tab factories -------------------------------------------------
        def _new_view(self) -> QWebEngineView:
            view = QWebEngineView()
            view.setPage(ShellPage(self))
            view.titleChanged.connect(lambda t, v=view: self._set_title(v, t))
            view.iconChanged.connect(lambda i, v=view: self._set_icon(v, i))
            return view

        def add_tab(self, focus: bool = True) -> QWebEngineView:
            """Empty tab whose page Qt will navigate (used by createWindow)."""
            view = self._new_view()
            idx = self.tabs.addTab(view, "Loading…")
            if focus:
                self.tabs.setCurrentIndex(idx)
            return view

        def new_home_tab(self, focus: bool = False) -> QWebEngineView:
            view = self._new_view()
            view.load(QUrl(url + "/?shell=1"))
            idx = self.tabs.addTab(view, "Feed")
            if focus:
                self.tabs.setCurrentIndex(idx)
            return view

        # ---- tab lifecycle -------------------------------------------------
        def close_tab(self, index: int) -> None:
            widget = self.tabs.widget(index)
            self.tabs.removeTab(index)
            if widget is not None:
                widget.deleteLater()
            if self.tabs.count() == 0:   # never leave an empty window
                self.new_home_tab(focus=True)

        def close_current(self) -> None:
            self.close_tab(self.tabs.currentIndex())

        def _set_title(self, view, title: str) -> None:
            idx = self.tabs.indexOf(view)
            if idx >= 0:
                self.tabs.setTabText(idx, (title or "").strip() or "Untitled")
            if view is self.tabs.currentWidget():
                self.setWindowTitle(((title or "").strip() or "skroli"))

        def _set_icon(self, view, icon) -> None:
            idx = self.tabs.indexOf(view)
            if idx >= 0:
                self.tabs.setTabIcon(idx, icon)

        def _on_current_changed(self, _index: int) -> None:
            view = self.tabs.currentWidget()
            if view is not None:
                self.setWindowTitle((view.title() or "skroli").strip() or "skroli")

        # ---- input ---------------------------------------------------------
        def _wire_shortcuts(self) -> None:
            QShortcut(QKeySequence.StandardKey.AddTab, self,
                      activated=lambda: self.new_home_tab(focus=True))
            QShortcut(QKeySequence.StandardKey.Close, self, activated=self.close_current)
            QShortcut(QKeySequence("Ctrl+W"), self, activated=self.close_current)
            QShortcut(QKeySequence.StandardKey.NextChild, self,
                      activated=lambda: self._cycle(1))
            QShortcut(QKeySequence("Ctrl+Tab"), self, activated=lambda: self._cycle(1))
            QShortcut(QKeySequence("Ctrl+Shift+Tab"), self, activated=lambda: self._cycle(-1))

        def _cycle(self, delta: int) -> None:
            n = self.tabs.count()
            if n:
                self.tabs.setCurrentIndex((self.tabs.currentIndex() + delta) % n)

        def eventFilter(self, obj, event):  # noqa: N802 (Qt naming)
            from PySide6.QtCore import QEvent
            if obj is self.tabs.tabBar() and event.type() == QEvent.Type.MouseButtonRelease:
                if event.button() == Qt.MouseButton.MiddleButton:
                    i = self.tabs.tabBar().tabAt(event.position().toPoint())
                    if i >= 0:
                        self.close_tab(i)
                        return True
            return super().eventFilter(obj, event)

    window = Shell()
    window.show()
    app.exec()
