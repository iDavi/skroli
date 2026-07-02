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
  height: 44px; padding: 0 8px 0 14px;
  border: 0; border-right: 1px solid #605b46;
  font-family: "Libertinus Math", "Libertinus Serif", Georgia, serif;
  font-size: 14px;
}
QTabBar#tabbar::tab:hover { background: #56523f; }
QTabBar#tabbar::tab:selected {
  background: #56523f; color: #f5f3ec; border-bottom: 2px solid #c9b27a;
}
QToolButton#tclose {
  background: transparent; border: 0; color: #959389;
  font-size: 15px; padding: 0 2px; margin-left: 4px;
}
QToolButton#tclose:hover { color: #f5f3ec; }

QToolButton#plus {
  background: transparent; color: #959389; border: 0;
  font-size: 20px; padding: 4px 14px;
}
QToolButton#plus:hover { background: #56523f; color: #f5f3ec; }

/* macOS traffic-light buttons (frameless removes the real ones, so these are
   pixel look-alikes: same colors/size, and ×/–/+ glyphs show on hover) */
#macclose, #macmin, #maczoom {
  border: 0; min-width: 12px; max-width: 12px; min-height: 12px; max-height: 12px;
  border-radius: 6px; font-size: 9px; font-weight: bold;
}
#macclose { background: #ff5f57; color: rgba(74,0,0,0.55); }
#macmin   { background: #febc2e; color: rgba(89,55,0,0.55); }
#maczoom  { background: #28c840; color: rgba(0,52,0,0.55); }

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
    import os
    import sys

    # Rein Chromium in BEFORE Qt spins it up: share renderer processes across
    # tabs instead of one-per-tab, and use low-end-device mode (smaller tiles &
    # caches). Respect any flags the user already set.
    _flags = "--renderer-process-limit=4 --enable-low-end-device-mode"
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", _flags)

    from PySide6.QtCore import QEvent, QRect, QTimer, QUrl, Qt
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
    profile.setHttpCacheMaximumSize(64 * 1024 * 1024)   # cap disk/mem cache

    RESIZE_MARGIN = 6   # px of grabbable border around the content for resizing

    class TabBar(QTabBar):
        """Browser-style tab bar: tabs shrink to share the available width when
        there are many, the empty area drags the window, and double-clicking the
        empty area opens a new tab."""

        def __init__(self, shell):
            super().__init__()
            self._shell = shell
            self._press = None
            self._origin = None

        def tabSizeHint(self, index):  # noqa: N802
            hint = super().tabSizeHint(index)
            n = self.count()
            if n > 0 and self.width() > 0:
                share = self.width() // n
                hint.setWidth(max(56, min(220, share)))
            return hint

        def _on_empty(self, pos):
            return self.tabAt(pos) < 0

        def mouseDoubleClickEvent(self, event):  # noqa: N802
            if event.button() == Qt.MouseButton.LeftButton and self._on_empty(event.position().toPoint()):
                self._shell.new_home_tab(focus=True)
                event.accept()
                return
            super().mouseDoubleClickEvent(event)

        def mousePressEvent(self, event):  # noqa: N802
            if event.button() == Qt.MouseButton.LeftButton and self._on_empty(event.position().toPoint()):
                self._press = event.globalPosition().toPoint()
                self._origin = self._shell.frameGeometry().topLeft()
                event.accept()
                return
            super().mousePressEvent(event)

        def mouseMoveEvent(self, event):  # noqa: N802
            if self._press is not None:
                self._shell.move(self._origin + (event.globalPosition().toPoint() - self._press))
                event.accept()
                return
            super().mouseMoveEvent(event)

        def mouseReleaseEvent(self, event):  # noqa: N802
            if self._press is not None:
                self._press = None
                self._origin = None
                event.accept()
                return
            super().mouseReleaseEvent(event)

    class ResizeFrame(QWidget):
        """Holds the web view with a thin border margin; the margin (the only
        part not covered by the event-swallowing web surface) resizes the window.
        Uses local mouse events — no app-wide event filter (that crashed with
        QtWebEngine)."""

        def __init__(self, shell):
            super().__init__()
            self._shell = shell
            self.setMouseTracking(True)

        def mousePressEvent(self, event):  # noqa: N802
            if event.button() == Qt.MouseButton.LeftButton:
                edges = self._shell._edges_at(event.globalPosition().toPoint())
                if edges:
                    self._shell._begin_resize(edges, event.globalPosition().toPoint())
                    event.accept()
                    return
            super().mousePressEvent(event)

        def mouseMoveEvent(self, event):  # noqa: N802
            if self._shell._rz_edges:
                self._shell._do_resize(event.globalPosition().toPoint())
                event.accept()
                return
            edges = self._shell._edges_at(event.globalPosition().toPoint())
            self.setCursor(self._shell._cursor_for(edges) if edges
                           else Qt.CursorShape.ArrowCursor)
            super().mouseMoveEvent(event)

        def mouseReleaseEvent(self, event):  # noqa: N802
            if self._shell._rz_edges:
                self._shell._rz_edges = None
                event.accept()
                return
            super().mouseReleaseEvent(event)

    class MacLights(QWidget):
        """macOS traffic-light look-alikes. The ×/–/+ glyphs appear only while
        the cursor is over the group, mirroring the real controls."""

        def __init__(self, shell):
            super().__init__()
            self.setObjectName("maclights")
            lay = QHBoxLayout(self)
            lay.setContentsMargins(13, 0, 10, 0)
            lay.setSpacing(8)
            self._close = shell._btn("macclose", "Close", shell.close)
            self._min = shell._btn("macmin", "Minimize", shell.showMinimized)
            self._zoom = shell._btn("maczoom", "Zoom", shell.toggle_max)
            for b in (self._close, self._min, self._zoom):
                lay.addWidget(b)

        def enterEvent(self, event):  # noqa: N802
            self._close.setText("×")   # ×
            self._min.setText("–")     # –
            self._zoom.setText("+")
            super().enterEvent(event)

        def leaveEvent(self, event):  # noqa: N802
            for b in (self._close, self._min, self._zoom):
                b.setText("")
            super().leaveEvent(event)

    class ShellPage(QWebEnginePage):
        """Routes window.open / target=_blank / modified clicks to a new tab.

        Parented to its *view* (not the window) so closing a tab actually frees
        the page and its render process — otherwise every closed tab leaks a
        whole Chromium page and the app eventually crashes."""

        def __init__(self, shell, view):
            super().__init__(profile, view)
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
            self.tabbar = TabBar(self)
            self.tabbar.setObjectName("tabbar")
            # We attach our own close button on the RIGHT of each tab (macOS Qt
            # would otherwise put the built-in one on the left, by the lights).
            self.tabbar.setTabsClosable(False)
            self.tabbar.setMovable(True)
            self.tabbar.setExpanding(False)
            self.tabbar.setDrawBase(False)
            self.tabbar.setElideMode(Qt.TextElideMode.ElideRight)
            self.tabbar.currentChanged.connect(self._on_current)
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
                row.addWidget(MacLights(self))
            row.addWidget(self.tabbar, 1)   # fills the row; empty area drags
            row.addWidget(plus)
            if not is_mac:
                row.addWidget(self._win_controls())

            # manual edge-resize state (frameless windows get none for free)
            self._rz_edges = None
            self._rz_geo = None
            self._rz_pos = None

            # background-tab lifecycle (memory): freeze background tabs when idle
            self._freeze_timer = QTimer(self)
            self._freeze_timer.setSingleShot(True)
            self._freeze_timer.timeout.connect(self._freeze_background)

            # The web view's surface swallows mouse events, so leave a thin
            # border of plain olive around it that the window can be resized by.
            content = ResizeFrame(self)
            cl = QVBoxLayout(content)
            cl.setContentsMargins(RESIZE_MARGIN, 0, RESIZE_MARGIN, RESIZE_MARGIN)
            cl.setSpacing(0)
            cl.addWidget(self.stack)

            central = QWidget()
            col = QVBoxLayout(central)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(0)
            col.addWidget(top)
            col.addWidget(content, 1)
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
            view.setPage(ShellPage(self, view))   # page owned by the view
            view.titleChanged.connect(lambda t, v=view: self._set_title(v, t))
            view.iconChanged.connect(lambda i, v=view: self._set_icon(v, i))
            return view

        def _attach_close(self, index: int) -> None:
            btn = QToolButton()
            btn.setObjectName("tclose")
            btn.setText("×")
            btn.setToolTip("Close tab")
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, b=btn: self._close_for_button(b))
            self.tabbar.setTabButton(index, QTabBar.ButtonPosition.RightSide, btn)

        def _close_for_button(self, btn) -> None:
            for i in range(self.tabbar.count()):
                if self.tabbar.tabButton(i, QTabBar.ButtonPosition.RightSide) is btn:
                    self.close_tab(i)
                    return

        def add_tab(self, focus: bool = True) -> QWebEngineView:
            view = self._new_view()
            idx = self.stack.addWidget(view)
            self.tabbar.addTab("Loading…")
            self._attach_close(idx)
            if focus:
                self.tabbar.setCurrentIndex(idx)
            return view

        def new_home_tab(self, focus: bool = False) -> QWebEngineView:
            view = self._new_view()
            idx = self.stack.addWidget(view)
            self.tabbar.addTab("Feed")
            self._attach_close(idx)
            view.load(QUrl(url + "/?shell=1"))
            if focus:
                self.tabbar.setCurrentIndex(idx)
            return view

        def close_tab(self, index: int) -> None:
            view = self.stack.widget(index)
            self.tabbar.removeTab(index)
            if view is not None:
                self.stack.removeWidget(view)
                # Tear the page down explicitly so its render process is released
                # promptly (stop loading, drop the page, then free the view).
                page = view.page()
                if page is not None:
                    page.deleteLater()
                view.setParent(None)
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
                self._set_lifecycle(view, "active")   # wake it immediately
            # Background tabs: freeze after a short idle — stops their JS and
            # rendering (the multi-tab CPU/memory cost) while keeping the DOM.
            # We deliberately do NOT use the Discarded state: destroying and
            # reactivating renderers triggers stale-GPU-texture errors on macOS.
            self._freeze_timer.start(20_000)

        def _set_lifecycle(self, view, state: str) -> None:
            try:
                from PySide6.QtWebEngineCore import QWebEnginePage
                st = {"active": QWebEnginePage.LifecycleState.Active,
                      "frozen": QWebEnginePage.LifecycleState.Frozen}[state]
                page = view.page()
                if page is not None and page.lifecycleState() != st:
                    page.setLifecycleState(st)
            except Exception:  # noqa: BLE001 - lifecycle is an optimization only
                pass

        def _freeze_background(self) -> None:
            cur = self.stack.currentWidget()
            for i in range(self.stack.count()):
                v = self.stack.widget(i)
                if v is not cur:
                    self._set_lifecycle(v, "frozen")

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
            # ⌘/Ctrl+1..8 jump to a tab, ⌘/Ctrl+9 jumps to the last (browser style)
            for n in range(1, 9):
                QShortcut(QKeySequence(f"Ctrl+{n}"), self,
                          activated=lambda i=n - 1: self._select(i))
            QShortcut(QKeySequence("Ctrl+9"), self,
                      activated=lambda: self._select(self.tabbar.count() - 1))

        def _select(self, index: int) -> None:
            if 0 <= index < self.tabbar.count():
                self.tabbar.setCurrentIndex(index)

        def _cycle(self, delta: int) -> None:
            n = self.tabbar.count()
            if n:
                self.tabbar.setCurrentIndex((self.tabbar.currentIndex() + delta) % n)

        # ---- manual edge-resize -------------------------------------------
        def _edges_at(self, gp):
            """Which window edges (left/right/bottom) the global point is near."""
            edges = Qt.Edge(0)
            if self.isMaximized() or self.isFullScreen():
                return edges
            r = self.geometry()
            if not r.adjusted(-RESIZE_MARGIN, -RESIZE_MARGIN,
                              RESIZE_MARGIN, RESIZE_MARGIN).contains(gp):
                return edges
            m = RESIZE_MARGIN
            if abs(gp.x() - r.left()) <= m:
                edges |= Qt.Edge.LeftEdge
            if abs(gp.x() - r.right()) <= m:
                edges |= Qt.Edge.RightEdge
            if abs(gp.y() - r.bottom()) <= m:   # no top edge: it's the tab row
                edges |= Qt.Edge.BottomEdge
            return edges

        def _cursor_for(self, edges):
            le, re = Qt.Edge.LeftEdge, Qt.Edge.RightEdge
            be = Qt.Edge.BottomEdge
            if (edges & le and edges & be):
                return Qt.CursorShape.SizeBDiagCursor
            if (edges & re and edges & be):
                return Qt.CursorShape.SizeFDiagCursor
            if edges & (le | re):
                return Qt.CursorShape.SizeHorCursor
            if edges & be:
                return Qt.CursorShape.SizeVerCursor
            return Qt.CursorShape.ArrowCursor

        def _begin_resize(self, edges, gp):
            self._rz_edges = edges
            self._rz_geo = QRect(self.geometry())
            self._rz_pos = gp

        def _do_resize(self, gp):
            g = QRect(self._rz_geo)
            d = gp - self._rz_pos
            e = self._rz_edges
            if e & Qt.Edge.LeftEdge:
                g.setLeft(g.left() + d.x())
            if e & Qt.Edge.RightEdge:
                g.setRight(g.right() + d.x())
            if e & Qt.Edge.BottomEdge:
                g.setBottom(g.bottom() + d.y())
            mn = self.minimumSize()
            if g.width() < mn.width():
                if e & Qt.Edge.LeftEdge:
                    g.setLeft(g.right() - mn.width())
                else:
                    g.setRight(g.left() + mn.width())
            if g.height() < mn.height():
                g.setBottom(g.top() + mn.height())
            self.setGeometry(g)

        def eventFilter(self, obj, event):  # noqa: N802
            if (obj is self.tabbar
                    and event.type() == QEvent.Type.MouseButtonRelease
                    and event.button() == Qt.MouseButton.MiddleButton):
                i = self.tabbar.tabAt(event.position().toPoint())
                if i >= 0:
                    self.close_tab(i)
                    return True
            return super().eventFilter(obj, event)

    window = Shell()
    window.show()
    app.exec()
