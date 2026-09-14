"""
PDF Folder Viewer
==================

A lightweight desktop app for browsing a folder of PDFs (e.g. a folder of
academic papers) one at a time, without needing to keep dozens of browser
tabs open.

Features:
  - Open a folder (optionally flattening all subfolders into one list)
  - Sidebar of PDFs, sorted in natural order (paper2 before paper10)
  - Left / Right arrows: previous / next PAPER
  - Up / Down arrows: always just scroll the current page, nothing else
  - Fit Width: continuous, page-width-filling scrolling (the default)
  - Fit Page: one page at a time, scaled to fit the window's height, where
    Page Up / Page Down move exactly one page
  - When the window is maximized and the zoom level leaves horizontal
    slack (Fit Page, or zoomed below Fit Width), the page is centered in
    the middle of the whole window rather than the sidebar-shifted
    sub-panel. When the window isn't maximized, the page just centers in
    its own sub-panel as usual.

Only one PDF is ever loaded into memory at a time (a single QPdfDocument
is reused and reloaded on navigation), which is what keeps this light even
with folders containing hundreds of papers.

--------------------------------------------------------------------------
Run directly for testing (no compilation needed):

    pip install PySide6
    python pdf_viewer.py

--------------------------------------------------------------------------
Compile to a single executable with Nuitka:

    python -m nuitka --standalone --onefile --enable-plugin=pyside6 pdf_viewer.py

Notes:
  - The --enable-plugin=pyside6 flag is required. Without it, Nuitka won't
    bundle the Qt platform/PDF plugins and the compiled exe will fail to
    start or fail to render PDFs.
  - On Windows, add --windows-console-mode=disable (or the equivalent flag
    for your Nuitka version) if you don't want a console window behind the
    GUI.
  - If the compiled exe runs but shows a blank page, try adding
    --include-qt-plugins=all to force-bundle every Qt plugin.
--------------------------------------------------------------------------
"""

import sys
from pathlib import Path
from re import split as re_split

from PySide6.QtCore import Qt, QEvent, QPointF
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QSplitter,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QCheckBox,
    QLabel,
    QToolBar,
    QFileDialog,
    QMessageBox,
    QAbstractSlider,
)
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView


def natural_sort_key(text: str):
    """Split text into text/number chunks so e.g. 'paper2' sorts before
    'paper10' (a plain string sort would put '10' before '2')."""
    chunks = re_split(r"(\d+)", text.lower())
    return [int(chunk) if chunk.isdigit() else chunk for chunk in chunks]


def find_pdfs(folder: Path, flatten: bool = False) -> list[Path]:
    """Return the PDFs under *folder*, in natural sort order.

    If flatten is True, PDFs in every subfolder are included too (the
    files on disk are untouched - this only affects what gets listed).
    """
    if flatten:
        candidates = folder.rglob("*")
    else:
        candidates = folder.iterdir()

    pdfs = [p for p in candidates if p.is_file() and p.suffix.lower() == ".pdf"]
    pdfs.sort(key=lambda p: natural_sort_key(str(p.relative_to(folder))))
    return pdfs


class PdfViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Folder Viewer")
        self.resize(1200, 850)

        self.pdf_paths: list[Path] = []
        self.current_index: int = -1
        self.current_folder: Path | None = None
        self.fit_page_mode: bool = False

        self.document = QPdfDocument(self)
        self.document.statusChanged.connect(self._on_status_changed)

        self._build_ui()
        self._build_shortcuts()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        open_btn = QPushButton("Open Folder…")
        open_btn.clicked.connect(self.open_folder)
        toolbar.addWidget(open_btn)

        self.flatten_checkbox = QCheckBox("Flatten subfolders")
        self.flatten_checkbox.stateChanged.connect(self._on_flatten_toggled)
        toolbar.addWidget(self.flatten_checkbox)

        toolbar.addSeparator()

        zoom_out_btn = QPushButton("Zoom −")
        zoom_out_btn.clicked.connect(self.zoom_out)
        toolbar.addWidget(zoom_out_btn)

        zoom_in_btn = QPushButton("Zoom +")
        zoom_in_btn.clicked.connect(self.zoom_in)
        toolbar.addWidget(zoom_in_btn)

        fit_width_btn = QPushButton("Fit Width")
        fit_width_btn.clicked.connect(self.fit_width)
        toolbar.addWidget(fit_width_btn)

        fit_page_btn = QPushButton("Fit Page")
        fit_page_btn.clicked.connect(self.fit_page)
        toolbar.addWidget(fit_page_btn)

        self.status_label = QLabel("No folder opened")
        self.statusBar().addPermanentWidget(self.status_label)

        # Sidebar: list of PDFs in the opened folder.
        self.sidebar = QListWidget()
        self.sidebar.currentRowChanged.connect(self.load_index)

        # Main PDF view: native Qt PDF widget, scrollable/zoomable already.
        self.view = QPdfView()
        self.view.setDocument(self.document)
        self.view.setPageMode(QPdfView.PageMode.MultiPage)
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.view.verticalScrollBar().setSingleStep(80)

        # The view sits in a container with an invisible spacer on its
        # right, matching the sidebar's current width. QPdfView centers
        # its page *within itself*, but since it only occupies the space
        # to the right of the sidebar, that self-centering looks pushed
        # right relative to the whole window. Mirroring the sidebar's
        # width on the other side makes the view's own bounds symmetric
        # about the window's center, so pages with slack space end up
        # visually centered in the window. This is only worth doing when
        # the window is maximized (otherwise the window itself is already
        # positioned/sized how the user wants, so plain sub-panel
        # centering is left alone) and only in zoom modes that actually
        # leave horizontal slack (Fit-to-width fills the view edge to
        # edge, so there's nothing to center).
        self.right_spacer = QWidget()
        self.right_spacer.setFixedWidth(0)

        view_container = QWidget()
        view_layout = QHBoxLayout(view_container)
        view_layout.setContentsMargins(0, 0, 0, 0)
        view_layout.setSpacing(0)
        view_layout.addWidget(self.view, 1)
        view_layout.addWidget(self.right_spacer, 0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(view_container)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([250, 950])
        self.splitter.splitterMoved.connect(lambda *_: self._update_center_spacer())

        self.setCentralWidget(self.splitter)
        self._update_center_spacer()

    def _build_shortcuts(self):
        # Arrow keys and Ctrl+wheel are handled as an application-wide
        # event filter (rather than QShortcuts) so they fire no matter
        # which child widget currently has keyboard focus - see
        # eventFilter() below.
        QApplication.instance().installEventFilter(self)

        zoom_in_sc = QShortcut(QKeySequence("Ctrl+="), self)
        zoom_in_sc.activated.connect(self.zoom_in)

        zoom_out_sc = QShortcut(QKeySequence("Ctrl+-"), self)
        zoom_out_sc.activated.connect(self.zoom_out)

        fit_sc = QShortcut(QKeySequence("Ctrl+0"), self)
        fit_sc.activated.connect(self.fit_width)

    # ------------------------------------------------------------- events
    def eventFilter(self, obj, event):
        event_type = event.type()

        if event_type == QEvent.Type.KeyPress:
            key = event.key()

            if key == Qt.Key.Key_Left:
                self.previous_pdf()
                return True
            if key == Qt.Key.Key_Right:
                self.next_pdf()
                return True

            # Up/Down are reserved exclusively for scrolling the current
            # page - never for changing the sidebar selection or the
            # open paper.
            scrollbar = self.view.verticalScrollBar()
            if key == Qt.Key.Key_Down:
                scrollbar.triggerAction(QAbstractSlider.SliderAction.SliderSingleStepAdd)
                return True
            if key == Qt.Key.Key_Up:
                scrollbar.triggerAction(QAbstractSlider.SliderAction.SliderSingleStepSub)
                return True

            # In Fit Page mode, Page Up/Down move exactly one page.
            if self.fit_page_mode:
                if key == Qt.Key.Key_PageDown:
                    self._step_page(1)
                    return True
                if key == Qt.Key.Key_PageUp:
                    self._step_page(-1)
                    return True

        elif event_type == QEvent.Type.Wheel:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                if event.angleDelta().y() > 0:
                    self.zoom_in()
                else:
                    self.zoom_out()
                return True

        return super().eventFilter(obj, event)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange:
            self._update_center_spacer()
        super().changeEvent(event)

    def _on_status_changed(self, status):
        if status == QPdfDocument.Status.Error and self.pdf_paths:
            name = self.pdf_paths[self.current_index].name
            self.status_label.setText(f"Failed to load: {name} ({self.document.error()})")

    # ---------------------------------------------------------- folder / flatten
    def open_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Open Folder of PDFs")
        if not folder:
            return
        self._load_folder(Path(folder))

    def _on_flatten_toggled(self, _state):
        if self.current_folder is not None:
            self._load_folder(self.current_folder)

    def _load_folder(self, folder_path: Path):
        flatten = self.flatten_checkbox.isChecked()
        pdfs = find_pdfs(folder_path, flatten=flatten)

        if not pdfs:
            where = "that folder or its subfolders" if flatten else "that folder"
            QMessageBox.warning(self, "No PDFs found", f"Couldn't find any PDF files in {where}.")
            return

        self.current_folder = folder_path
        self.pdf_paths = pdfs
        self.sidebar.blockSignals(True)
        self.sidebar.clear()
        for path in pdfs:
            QListWidgetItem(str(path.relative_to(folder_path)), self.sidebar)
        self.sidebar.blockSignals(False)

        self.setWindowTitle(f"PDF Folder Viewer — {folder_path.name}")
        self.sidebar.setCurrentRow(0)  # triggers load_index(0)

    # ---------------------------------------------------------- navigation
    def load_index(self, index: int):
        if index < 0 or index >= len(self.pdf_paths):
            return
        self.current_index = index
        path = self.pdf_paths[index]
        self.document.load(str(path))
        self.status_label.setText(f"{index + 1} of {len(self.pdf_paths)}  —  {path.relative_to(self.current_folder)}")
        if self.sidebar.currentRow() != index:
            self.sidebar.setCurrentRow(index)

    def previous_pdf(self):
        if self.current_index > 0:
            self.sidebar.setCurrentRow(self.current_index - 1)

    def next_pdf(self):
        if self.current_index < len(self.pdf_paths) - 1:
            self.sidebar.setCurrentRow(self.current_index + 1)

    def _step_page(self, delta: int):
        nav = self.view.pageNavigator()
        target = nav.currentPage() + delta
        if 0 <= target < self.document.pageCount():
            nav.jump(target, QPointF(), 0.0)

    # ---------------------------------------------------------- zoom / centering
    def _update_center_spacer(self):
        """Keep the right-hand spacer in sync with the sidebar's width.
        Only active when the window is maximized AND the current zoom
        mode leaves horizontal slack to center within."""
        has_slack_mode = self.view.zoomMode() != QPdfView.ZoomMode.FitToWidth
        if self.isMaximized() and has_slack_mode:
            self.right_spacer.setFixedWidth(self.sidebar.width())
        else:
            self.right_spacer.setFixedWidth(0)

    def zoom_in(self):
        self.fit_page_mode = False
        self.view.setPageMode(QPdfView.PageMode.MultiPage)
        self.view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.view.setZoomFactor(self.view.zoomFactor() * 1.15)
        self._update_center_spacer()

    def zoom_out(self):
        self.fit_page_mode = False
        self.view.setPageMode(QPdfView.PageMode.MultiPage)
        self.view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.view.setZoomFactor(self.view.zoomFactor() / 1.15)
        self._update_center_spacer()

    def fit_width(self):
        self.fit_page_mode = False
        self.view.setPageMode(QPdfView.PageMode.MultiPage)
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self._update_center_spacer()

    def fit_page(self):
        # One page at a time, scaled to fit the window - Page Up/Down
        # then move exactly one page (handled in eventFilter above).
        self.fit_page_mode = True
        self.view.setPageMode(QPdfView.PageMode.SinglePage)
        self.view.setZoomMode(QPdfView.ZoomMode.FitInView)
        self._update_center_spacer()


def main():
    app = QApplication(sys.argv)
    window = PdfViewer()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()