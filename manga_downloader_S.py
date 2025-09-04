import os
import sys
import json
import importlib.util
import requests
import collections
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from pathlib import Path


from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QTextEdit, QLabel,
    QFileDialog, QCheckBox, QProgressBar, QSpinBox, QTabWidget, QMessageBox, QMenuBar, QMenu,
    QListWidget, QListWidgetItem, QComboBox, QGroupBox, QSpacerItem, QSizePolicy, QDialog
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction, QIcon

QTextEditClass = QTextEdit
pyqtSignal = Signal

from PIL import Image
import glob
# PDF editing import (pypdf or PyPDF2)
try:
    import pypdf
except ImportError:
    try:
        import PyPDF2 as pypdf
    except ImportError:
        pypdf = None
# Selenium imports
try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.chrome.options import Options as ChromeOptions
except ImportError:
    webdriver = None
    By = None
    ChromeOptions = None

def load_plugins():
    plugins = []
    plugins_dir = os.path.join(os.path.dirname(__file__), "plugins")
    if not os.path.isdir(plugins_dir):
        return plugins
    import inspect
    for fname in os.listdir(plugins_dir):
        if fname.endswith("_plugin.py"):
            path = os.path.join(plugins_dir, fname)
            spec = importlib.util.spec_from_file_location(fname[:-3], path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            for obj in mod.__dict__.values():
                if inspect.isclass(obj) and hasattr(obj, "can_handle") and hasattr(obj, "get_image_urls"):
                    # Skip abstract base classes
                    if getattr(obj, "__abstractmethods__", None):
                        continue
                    plugins.append(obj())
    return plugins




class MangaDownloader(QWidget):
    def browse_poppler(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select pdftoppm Executable", "", "Executable Files (*.exe);;All Files (*)")
        if path:
            self.poppler_path_field.setText(path)
            self.save_settings("poppler_path", path)
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Manga Image Downloader")
        self.setGeometry(100, 100, 500, 350)
        self.plugins = load_plugins()
        self.restore_queue_state()
        # Connect DownloadThread selenium error signal to dialog
        self._connect_selenium_error_signal = False
    # ...existing code...

        # Main tab widget
        self.tabs = QTabWidget(self)
        self.downloader_tab = QWidget()
        self.pdf_tab = QWidget()
        self.settings_tab = QWidget()
        self.tabs.addTab(self.downloader_tab, "Downloader")
        self.tabs.insertTab(1, self.pdf_tab, "PDF")
        self.tabs.addTab(self.settings_tab, "Settings")

        # Downloader tab layout
        layout = QVBoxLayout()

        # PDF tab layout
        pdf_layout = QVBoxLayout()
        pdf_actions_group = QGroupBox("PDF Actions")
        pdf_actions_layout = QVBoxLayout()

        # Add Help/About menu
        self.menu_bar = QMenuBar(self)
        help_menu = QMenu("Help", self)
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)
        self.menu_bar.addMenu(help_menu)
        layout.setMenuBar(self.menu_bar)

        self.url_label = QLabel("Enter manga page URLs (one per line):")
        layout.addWidget(self.url_label)

        url_input_layout = QHBoxLayout()
        self.url_input = QTextEdit()
        self.url_input.setPlaceholderText("https://example.com/page1\nhttps://example.com/page2")
        self.url_input.setToolTip("Enter one manga page URL per line. Drag-and-drop or paste URLs here.")
        self.url_input.setAcceptDrops(True)
        self.url_input.installEventFilter(self)
        url_input_layout.addWidget(self.url_input)
        self.copy_urls_button = QPushButton("Copy URLs")
        self.copy_urls_button.setToolTip("Copy all URLs in the input field to clipboard")
        self.copy_urls_button.clicked.connect(self.copy_urls_to_clipboard)
        url_input_layout.addWidget(self.copy_urls_button)
        self.clear_urls_button = QPushButton("Clear URLs")
        self.clear_urls_button.setToolTip("Clear all URLs from the input field")
        self.clear_urls_button.clicked.connect(self.clear_urls)
        url_input_layout.addWidget(self.clear_urls_button)
        layout.addLayout(url_input_layout)

        # Download queue list
        self.queue_list = QListWidget()
        self.queue_list.setMinimumHeight(120)
        self.queue_list.setToolTip("Shows the status of each URL in the download queue. Double-click a failed item to retry.")
        layout.addWidget(self.queue_list)

        # Log filter and log buttons layout
        log_control_layout = QHBoxLayout()
        # Log level filter dropdown
        self.log_filter_combo = QComboBox()
        self.log_filter_combo.addItems(["All", "Info/Success", "Warning", "Error"])
        self.log_filter_combo.setToolTip("Filter log messages by level")
        self.log_filter_combo.currentIndexChanged.connect(self.apply_log_filter)
        log_control_layout.addWidget(self.log_filter_combo)
        # Copy Log button
        self.copy_log_button = QPushButton("Copy Log")
        self.copy_log_button.setToolTip("Copy all status messages to clipboard")
        self.copy_log_button.clicked.connect(self.copy_log_to_clipboard)
        log_control_layout.addWidget(self.copy_log_button)
        # Save Log button
        self.save_log_button = QPushButton("Save Log")
        self.save_log_button.setToolTip("Save all status messages to a file")
        self.save_log_button.clicked.connect(self.save_log_to_file)
        log_control_layout.addWidget(self.save_log_button)
        # Clear Log button
        self.clear_log_button = QPushButton("Clear Log")
        self.clear_log_button.setToolTip("Clear all status messages from the status box")
        self.clear_log_button.clicked.connect(self.clear_log)
        log_control_layout.addWidget(self.clear_log_button)
        layout.addLayout(log_control_layout)

        # Save location selection
        save_layout = QHBoxLayout()
        self.save_label = QLabel("Save location:")
        save_layout.addWidget(self.save_label)
        self.save_path_field = QLineEdit()
        self.save_path_field.setReadOnly(True)
        self.save_path_field.setToolTip("Current folder where images and PDFs will be saved")
        self.save_path_field.setText(self.load_last_save_location())
        save_layout.addWidget(self.save_path_field)
        self.browse_button = QPushButton("Browse")
        self.browse_button.setToolTip("Choose a folder to save downloaded images and PDFs")
        self.browse_button.clicked.connect(self.browse_folder)
        save_layout.addWidget(self.browse_button)
        self.open_folder_button = QPushButton("Open Folder")
        self.open_folder_button.setToolTip("Open the current save folder in your file manager")
        self.open_folder_button.clicked.connect(self.open_download_folder)
        save_layout.addWidget(self.open_folder_button)
        layout.addLayout(save_layout)

        # Merge mode dropdown
        self.merge_mode_combo = QComboBox()
        self.merge_mode_combo.addItems(["Merge Images", "Merge PDFs"])
        self.merge_mode_combo.setToolTip("Select merge mode: merge images or merge PDFs in subfolders")
        pdf_actions_layout.addWidget(self.merge_mode_combo)

        # Open PDF button (hidden by default)
        self.open_pdf_button = QPushButton("Open Last Merged PDF")
        self.open_pdf_button.setVisible(False)
        self.open_pdf_button.clicked.connect(self.open_last_pdf)
        pdf_actions_layout.addWidget(self.open_pdf_button)

        # Select Parent Folder button
        self.select_parent_folder_button = QPushButton("Select Parent Folder")
        self.select_parent_folder_button.setToolTip("Choose the parent folder containing subfolders to merge")
        self.select_parent_folder_button.clicked.connect(self.select_parent_folder)
        pdf_actions_layout.addWidget(self.select_parent_folder_button)

        # Select Folders button
        self.select_folders_button = QPushButton("Select Folders to Merge")
        self.select_folders_button.setToolTip("Choose specific subfolders to merge")
        self.select_folders_button.clicked.connect(self.open_select_folders_dialog)
        pdf_actions_layout.addWidget(self.select_folders_button)

        # Merge button
        self.merge_button = QPushButton("Merge (Images or PDFs)")
        self.merge_button.setToolTip("Merge downloaded images or PDFs in subfolders, depending on selected mode")
        self.merge_button.clicked.connect(self.merge_to_pdf)
        pdf_actions_layout.addWidget(self.merge_button)

        # Volume button
        self.volume_button = QPushButton("Compile Chapters to Volume PDF")
        self.volume_button.setToolTip("Combine all chapter PDFs into a single volume PDF")
        self.volume_button.clicked.connect(self.compile_volume_pdf)
        pdf_actions_layout.addWidget(self.volume_button)

        # Edit PDF button
        self.edit_pdf_button = QPushButton("Edit PDF")
        self.edit_pdf_button.setToolTip("Delete or reorder pages in a PDF file")
        self.edit_pdf_button.clicked.connect(self.open_edit_pdf_dialog)
        pdf_actions_layout.addWidget(self.edit_pdf_button)
        pdf_actions_group.setLayout(pdf_actions_layout)
        pdf_layout.addWidget(pdf_actions_group)
        # PDF status/feedback area
        self.pdf_status_box = QTextEditClass()
        self.pdf_status_box.setReadOnly(True)
        self.pdf_status_box.setMinimumHeight(40)
        self.pdf_status_box.setMaximumHeight(80)
        self.pdf_status_box.setToolTip("PDF operation status and feedback messages")
        pdf_layout.addWidget(self.pdf_status_box)
        pdf_layout.addItem(QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        self.pdf_tab.setLayout(pdf_layout)

        # Download button
        self.download_button = QPushButton("Download Images")
        self.download_button.setToolTip("Start downloading images from the listed URLs")
        self.download_button.clicked.connect(self.download_images)
        layout.addWidget(self.download_button)

        # (Global Pause/Resume buttons removed)

        # Status box
        self.status_box = QTextEdit()
        self.status_box.setReadOnly(True)
        self.status_box.setToolTip("Status messages, errors, and progress will appear here")
        layout.addWidget(self.status_box)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.downloader_tab.setLayout(layout)
        # Save queue state on close
        self._orig_closeEvent = self.closeEvent
        self.closeEvent = self._on_close_event

        # Settings tab layout (with controls)
        settings_layout = QVBoxLayout()
        # Concurrency
        concurrency_layout = QHBoxLayout()
        concurrency_label = QLabel("Concurrent downloads:")
        concurrency_layout.addWidget(concurrency_label)
        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setMinimum(1)
        self.concurrency_spin.setMaximum(32)
        self.concurrency_spin.setValue(6)
        self.concurrency_spin.setToolTip("Number of images to download at the same time")
        concurrency_layout.addWidget(self.concurrency_spin)
        settings_layout.addLayout(concurrency_layout)
        # Auto-merge
        self.auto_merge_checkbox = QCheckBox("Auto-merge images to PDF after download")
        self.auto_merge_checkbox.setToolTip("Automatically merge downloaded images into a PDF after each chapter")
        settings_layout.addWidget(self.auto_merge_checkbox)
        # Dependency warning/info label
        self.dependency_warning_label = QLabel()
        self.dependency_warning_label.setWordWrap(True)
        self.dependency_warning_label.setStyleSheet("color: #B22222; font-weight: bold;")
        settings_layout.addWidget(self.dependency_warning_label)
        # Log Number of Images Found (automatic, no checkbox)
        # (No UI element, always log number of images found before downloading)
        # Selenium
        self.selenium_checkbox = QCheckBox("Use Selenium for image extraction (for JS-heavy sites)")
        self.selenium_checkbox.setToolTip("Enable Selenium for sites that require JavaScript to load images. Requires ChromeDriver/GeckoDriver.")
        self.selenium_checkbox.stateChanged.connect(self.validate_dependencies)
        settings_layout.addWidget(self.selenium_checkbox)
        # Headless
        self.headless_checkbox = QCheckBox("Headless Mode (no browser window)")
        self.headless_checkbox.setChecked(True)
        self.headless_checkbox.setToolTip("Run Selenium in headless mode (no visible browser window). Uncheck to see the browser.")
        settings_layout.addWidget(self.headless_checkbox)
        # Selenium driver path
        selenium_driver_layout = QHBoxLayout()
        self.selenium_driver_path_field = QLineEdit()
        self.selenium_driver_path_field.setPlaceholderText("Path to ChromeDriver/GeckoDriver executable")
        self.selenium_driver_path_field.setToolTip(
            "Select the path to your Selenium WebDriver executable (e.g., chromedriver.exe or geckodriver.exe).\n"
            "Required only for JS-heavy sites. Download from https://chromedriver.chromium.org/ or https://github.com/mozilla/geckodriver/releases.\n"
            "Leave blank to use system default."
        )
        # Load saved path if available
        saved_driver_path = self.load_settings("selenium_driver_path", "")
        if saved_driver_path:
            self.selenium_driver_path_field.setText(saved_driver_path)
        selenium_driver_layout.addWidget(self.selenium_driver_path_field)
        self.selenium_driver_browse_button = QPushButton("Browse Driver")
        self.selenium_driver_browse_button.setToolTip("Browse for the Selenium WebDriver executable")
        self.selenium_driver_browse_button.clicked.connect(self.browse_selenium_driver)
        selenium_driver_layout.addWidget(self.selenium_driver_browse_button)
        # Add Test Selenium Driver button
        self.selenium_test_button = QPushButton("Test Selenium Driver")
        self.selenium_test_button.setToolTip("Test if the selected Selenium WebDriver is compatible and working.")
        self.selenium_test_button.clicked.connect(self.test_selenium_driver_compatibility)
        selenium_driver_layout.addWidget(self.selenium_test_button)
        settings_layout.addLayout(selenium_driver_layout)
    # ...existing code...
        # Poppler path configuration
        poppler_path_layout = QHBoxLayout()
        poppler_path_label = QLabel("Poppler pdftoppm path:")
        poppler_path_layout.addWidget(poppler_path_label)
        self.poppler_path_field = QLineEdit()
        self.poppler_path_field.setPlaceholderText("Path to pdftoppm executable (optional)")
        self.poppler_path_field.setToolTip("Set a custom path to the pdftoppm binary for PDF preview. Leave blank to auto-detect.")
        saved_poppler_path = self.load_settings("poppler_path", "")
        if saved_poppler_path:
            self.poppler_path_field.setText(saved_poppler_path)
        poppler_path_layout.addWidget(self.poppler_path_field)
        self.poppler_browse_button = QPushButton("Browse Poppler")
        self.poppler_browse_button.setToolTip("Browse for the pdftoppm executable")
        self.poppler_browse_button.clicked.connect(self.browse_poppler)
        poppler_path_layout.addWidget(self.poppler_browse_button)
        settings_layout.addLayout(poppler_path_layout)
        settings_layout.addStretch(1)
        self.settings_tab.setLayout(settings_layout)
        # Validate dependencies at startup
        self.validate_dependencies()

        # Main layout for the window
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.tabs)
        self.setLayout(main_layout)

    def _get_settings_path(self):
        # Store in user home directory for cross-platform consistency
        home = Path.home()
        return home / ".manga_downloader_settings.json"

    def save_settings(self, key, value):
        try:
            path = self._get_settings_path()
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = {}
            data[key] = value
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception:
            pass

    def load_settings(self, key, default=None):
        try:
            path = self._get_settings_path()
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data.get(key, default)
            else:
                return default
        except Exception:
            return default

    def browse_selenium_driver(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Selenium WebDriver Executable", "", "Executable Files (*.exe);;All Files (*)")
        if path:
            self.selenium_driver_path_field.setText(path)
            self.save_settings("selenium_driver_path", path)
            self.validate_dependencies()

    # Removed tray icon browse functionality

    def eventFilter(self, obj, event):
        # Drag-and-drop support for URLs and text files in url_input
        # Use QEvent type enums for compatibility
        from PySide6.QtCore import QEvent
        DragEnter = QEvent.Type.DragEnter
        Drop = QEvent.Type.Drop
        if obj == self.url_input:
            if event.type() == DragEnter:
                if event.mimeData().hasUrls() or event.mimeData().hasText():
                    event.acceptProposedAction()
                    return True
            elif event.type() == Drop:
                lines = []
                if event.mimeData().hasUrls():
                    for u in event.mimeData().urls():
                        local_path = u.toLocalFile()
                        if local_path and (local_path.endswith('.txt') or local_path.endswith('.csv')):
                            try:
                                with open(local_path, 'r', encoding='utf-8') as f:
                                    lines.extend(f.read().splitlines())
                            except Exception:
                                pass
                        else:
                            url = u.toString()
                            if url:
                                lines.append(url)
                elif event.mimeData().hasText():
                    text = event.mimeData().text()
                    lines.extend([line.strip() for line in text.splitlines() if line.strip()])
                urls = self._extract_valid_urls(lines)
                if urls:
                    current = self.url_input.toPlainText().strip()
                    if current:
                        self.url_input.setPlainText(current + '\n' + '\n'.join(urls))
                    else:
                        self.url_input.setPlainText('\n'.join(urls))
                    event.acceptProposedAction()
                    return True
        return super().eventFilter(obj, event)

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Download Folder", self.save_path_field.text())
        if folder:
            self.save_path_field.setText(folder)
            self.save_last_save_location(folder)

    
    def open_download_folder(self):
        folder = Path(self.save_path_field.text().strip())
        if not folder or not folder.is_dir():
            self.log("Download folder does not exist.")
            return
        try:
            if sys.platform.startswith('win'):
                os.startfile(str(folder))
            elif sys.platform.startswith('darwin'):
                import subprocess
                subprocess.Popen(['open', str(folder)])
            else:
                import subprocess
                subprocess.Popen(['xdg-open', str(folder)])
            self.log(f"Opened folder: {folder}")
        except Exception as e:
            self.log(f"Failed to open folder: {e}")

    def open_last_pdf(self):
        if hasattr(self, 'last_pdf_path') and self.last_pdf_path and os.path.isfile(self.last_pdf_path):
            try:
                if sys.platform.startswith('win'):
                    os.startfile(self.last_pdf_path)
                elif sys.platform.startswith('darwin'):
                    import subprocess
                    subprocess.Popen(['open', self.last_pdf_path])
                else:
                    import subprocess
                    subprocess.Popen(['xdg-open', self.last_pdf_path])
                self.log(f"Opened PDF: {self.last_pdf_path}")
            except Exception as e:
                self.log(f"Failed to open PDF: {e}")
        else:
            self.log("No PDF available to open.")

    def _get_save_location_path(self):
        # Store in user home directory for cross-platform consistency
        home = Path.home()
        return home / ".manga_downloader_last_save_location.json"

    def save_last_save_location(self, folder):
        try:
            path = self._get_save_location_path()
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"last_folder": folder}, f)
        except Exception:
            pass

    def load_last_save_location(self):
        try:
            path = self._get_save_location_path()
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("last_folder", str(Path.cwd() / "manga_images"))
        except Exception:
            return str(Path.cwd() / "manga_images")

    
    
    def show_about_dialog(self):
        about_text = (
            "<b>Manga Image Downloader</b><br><br>"
            "A cross-platform tool to download images and compile them into PDFs.<br><br>"
            "<b>How to Download Images:</b><br>"
            "1. Enter or paste manga/comic/web page URLs (one per line) in the main box.<br>"
            "2. (Optional) Use the Paste URLs button to quickly paste from clipboard.<br>"
            "3. (Optional) Drag-and-drop URLs or text files into the input field.<br>"
            "4. Choose a save location for images and PDFs.<br>"
            "5. Set the number of concurrent downloads (higher = faster, but more bandwidth).<br>"
            "6. Click <b>Download Images</b> to start.<br>"
            "7. Use <b>Merge Downloaded Images to PDF</b> for per-chapter PDFs, or enable auto-merge.<br>"
            "8. Use <b>Compile Chapters to Volume PDF</b> to combine all chapters into one PDF.<br><br>"
            "<b>PDF Editing:</b><br>"
            "- Use <b>Edit PDF</b> to delete or reorder pages in any PDF.<br>"
            "- If PDF preview is not available, you can still edit and save PDFs.<br><br>"
            "<b>PDF Preview Requirements:</b><br>"
            "- PDF preview uses <b>pdf2image</b> and <b>poppler</b>.<br>"
            "- If you see 'PDF preview not available', you can still edit PDFs.<br>"
            "- To enable preview on Windows:<br>"
            "  1. Download poppler from <a href='https://github.com/oschwartz10612/poppler-windows/releases/'>poppler-windows</a>.<br>"
            "  2. Extract the ZIP and add the <b>bin</b> folder to your system PATH.<br>"
            "  3. Install pdf2image: <code>pip install pdf2image</code><br>"
            #"- On macOS: <code>brew install poppler</code><br>" 'Wahala'
            #"- On Linux: <code>sudo apt install poppler-utils</code><br><br>"
            "<b>Troubleshooting:</b><br>"
            "- If images are missing extensions, the app will try to fix them automatically.<br>"
            "- If downloads fail, check your internet connection and site compatibility.<br>"
            "- For JS-heavy sites, enable Selenium mode and provide a compatible driver.<br><br>"
            "<b>Tips:</b><br>"
            "- Status messages are color-coded for clarity.<br>"
            "<b>Version:</b> 1.0<br>"
            "<b>Github:</b> https://github.com/Malz-arc/Manga_downloader_S<br>"
        )
        QMessageBox.about(self, "About Manga Image Downloader", about_text)

    def clear_log(self):
        self.status_box.clear()
        self._log_history = []

    def save_log_to_file(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "Save Log As", "log.txt", "Text Files (*.txt);;All Files (*)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                for entry in getattr(self, '_log_history', []):
                    f.write(f"[{entry['level'].upper()}] {entry['plain']}\n")

    def copy_urls_to_clipboard(self):
        clipboard = QApplication.clipboard()
        urls = self.url_input.toPlainText().strip()
        clipboard.setText(urls)

    def copy_log_to_clipboard(self):
        clipboard = QApplication.clipboard()
        # Remove HTML tags for plain text copy
        import re
        html = self.status_box.toHtml()
        # Extract text from HTML
        text = re.sub('<[^<]+?>', '', html)
        clipboard.setText(text.strip())

    def clear_urls(self):
        self.url_input.clear()

    def test_selenium_driver_compatibility(self):
        """
        Test if the selected Selenium WebDriver is compatible and working.
        Logs the result in the dependency warning label and main log.
        Prevents launching obviously invalid executables by checking --version output first.
        """
        import subprocess
        import shlex
        import platform
        driver_path = self.selenium_driver_path_field.text().strip() if hasattr(self, 'selenium_driver_path_field') else ''
        if not driver_path or not os.path.isfile(driver_path):
            self.log_error("Selenium driver path is not set or file does not exist.")
            self.dependency_warning_label.setText("Selenium driver path is not set or file does not exist.")
            self.dependency_warning_label.setVisible(True)
            return
        # Pre-check: run driver with --version and check output
        try:
            cmd = f'"{driver_path}" --version'
            # Use shell=False for security, but Windows needs special handling
            if platform.system() == "Windows":
                proc = subprocess.run(cmd, capture_output=True, text=True, shell=True, timeout=5)
            else:
                proc = subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=5)
            version_out = proc.stdout.strip() + proc.stderr.strip()
            if not ("ChromeDriver" in version_out or "GeckoDriver" in version_out):
                msg = f"Selected file is not a valid ChromeDriver or GeckoDriver. Output: {version_out}"
                self.log_error(msg)
                self.dependency_warning_label.setText(msg)
                self.dependency_warning_label.setStyleSheet("color: #B22222; font-weight: bold;")
                self.dependency_warning_label.setVisible(True)
                return
        except Exception as e:
            msg = f"Failed to check driver version: {e}"
            self.log_error(msg)
            self.dependency_warning_label.setText(msg)
            self.dependency_warning_label.setStyleSheet("color: #B22222; font-weight: bold;")
            self.dependency_warning_label.setVisible(True)
            return
        if webdriver is None or ChromeOptions is None:
            self.log_error("Selenium or Chrome WebDriver is not installed. Please install selenium and try again.")
            self.dependency_warning_label.setText("Selenium or Chrome WebDriver is not installed. Please install selenium and try again.")
            self.dependency_warning_label.setStyleSheet("color: #B22222; font-weight: bold;")
            self.dependency_warning_label.setVisible(True)
            return
        try:
            from selenium.webdriver.chrome.service import Service as ChromeService
            chrome_options = ChromeOptions()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--disable-gpu')
            driver = webdriver.Chrome(service=ChromeService(driver_path), options=chrome_options)
            driver.get("https://www.example.com/")
            title = driver.title
            driver.quit()
            msg = f"Selenium driver test succeeded. Page title: {title}"
            self.log_success(msg)
            self.dependency_warning_label.setText(msg)
            self.dependency_warning_label.setStyleSheet("color: #228B22; font-weight: bold;")
            self.dependency_warning_label.setVisible(True)
        except Exception as e:
            msg = f"Selenium driver test failed: {e}"
            self.log_error(msg)
            self.dependency_warning_label.setText(msg)
            self.dependency_warning_label.setStyleSheet("color: #B22222; font-weight: bold;")
            self.dependency_warning_label.setVisible(True)

    def validate_dependencies(self):
        import shutil
        import sys
        # Validate Selenium driver
        selenium_enabled = self.selenium_checkbox.isChecked() if hasattr(self, 'selenium_checkbox') else False
        driver_path = self.selenium_driver_path_field.text().strip() if hasattr(self, 'selenium_driver_path_field') else ''
        driver_ok = True
        driver_msg = ""
        if selenium_enabled:
            import subprocess, platform, shlex
            if not driver_path or not os.path.isfile(driver_path):
                driver_ok = False
                driver_msg = "Selenium driver not found. Please set the path to ChromeDriver or GeckoDriver.\n"
            elif not os.access(driver_path, os.X_OK):
                driver_ok = False
                driver_msg = "Selenium driver is not executable. Please check permissions.\n"
            else:
                # Version check
                try:
                    cmd = f'"{driver_path}" --version'
                    if platform.system() == "Windows":
                        proc = subprocess.run(cmd, capture_output=True, text=True, shell=True, timeout=5)
                    else:
                        proc = subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=5)
                    version_out = proc.stdout.strip() + proc.stderr.strip()
                    if not ("ChromeDriver" in version_out or "GeckoDriver" in version_out):
                        driver_ok = False
                        driver_msg += f"Selected file is not a valid ChromeDriver or GeckoDriver. Output: {version_out}\n"
                except Exception as e:
                    driver_ok = False
                    driver_msg += f"Failed to check driver version: {e}\n"
        # Validate poppler and pdf2image
        poppler_ok = False
        poppler_msg = ""
        poppler_bin = ""
        if sys.platform.startswith('win'):
            poppler_bin = shutil.which("pdftoppm.exe")
        else:
            poppler_bin = shutil.which("pdftoppm")
        if poppler_bin:
            poppler_ok = True
        else:
            # Check custom path from settings field
            custom_poppler_path = self.poppler_path_field.text().strip() if hasattr(self, 'poppler_path_field') else ''
            if custom_poppler_path and os.path.isfile(custom_poppler_path) and os.access(custom_poppler_path, os.X_OK):
                # Check filename ends with pdftoppm(.exe)
                exe_name = os.path.basename(custom_poppler_path).lower()
                if exe_name == "pdftoppm.exe" or exe_name == "pdftoppm":
                    poppler_ok = True
            if not poppler_ok:
                poppler_msg = "Poppler not found. PDF preview and some PDF features may not work.\n"
        # Check for pdf2image
        pdf2image_ok = False
        pdf2image_msg = ""
        try:
            import pdf2image
            pdf2image_ok = True
        except ImportError:
            pdf2image_msg = "pdf2image Python package not found. PDF preview and some PDF features may not work. Install with: pip install pdf2image\n"
        # Compose warning/instruction message
        msg = ""
        if not driver_ok:
            msg += driver_msg
            msg += "<b>Setup instructions for Selenium:</b><br>"
            msg += "Download ChromeDriver: <a href='https://chromedriver.chromium.org/downloads'>chromedriver.chromium.org</a><br>"
            msg += "Download GeckoDriver: <a href='https://github.com/mozilla/geckodriver/releases'>github.com/mozilla/geckodriver</a><br>"
            msg += "Set the path above and ensure it is executable.<br>"
        if not poppler_ok:
            msg += poppler_msg
            msg += "<b>Setup instructions for Poppler:</b><br>"
            msg += "Windows: Download from <a href='https://github.com/oschwartz10612/poppler-windows/releases/'>poppler-windows</a> and add the bin folder to your PATH.<br>"
            msg += "macOS: <code>brew install poppler</code><br>"
            msg += "Linux: <code>sudo apt install poppler-utils</code><br>"
        if not pdf2image_ok:
            msg += pdf2image_msg
            msg += "<b>Setup instructions for pdf2image:</b><br>"
            msg += "Install with: <code>pip install pdf2image</code><br>"
        self.dependency_warning_label.setText(msg)
        self.dependency_warning_label.setVisible(bool(msg))

    def log(self, message, level="info"):
        color = {
            "info": "#222",
            "success": "#228B22",
            "warning": "#FF8C00",
            "error": "#B22222"
        }.get(level, "#222")
        html = f'<span style="color:{color}">{message}</span>'
        # Store log history for filtering and saving (limit to 1000 entries)
        if not hasattr(self, '_log_history'):
            self._log_history = []
        import re
        plain = re.sub('<[^<]+?>', '', str(message))
        self._log_history.append({"level": level, "html": html, "plain": plain})
        max_log_entries = 1000
        if len(self._log_history) > max_log_entries:
            self._log_history = self._log_history[-max_log_entries:]
        self.apply_log_filter()

    def apply_log_filter(self):
        if not hasattr(self, '_log_history'):
            self._log_history = []
        filter_mode = self.log_filter_combo.currentText() if hasattr(self, 'log_filter_combo') else "All"
        self.status_box.clear()
        for entry in self._log_history:
            show = False
            if filter_mode == "All":
                show = True
            elif filter_mode == "Info/Success":
                show = entry["level"] in ("info", "success")
            elif filter_mode == "Warning":
                show = entry["level"] == "warning"
            elif filter_mode == "Error":
                show = entry["level"] == "error"
            if show:
                self.status_box.append(entry["html"])
        self.status_box.verticalScrollBar().setValue(self.status_box.verticalScrollBar().maximum())

    def log_error(self, message):
        self.log(message, level="error")

    def log_warning(self, message):
        self.log(message, level="warning")

    def log_success(self, message):
        self.log(message, level="success")

    def download_images(self):
        from urllib.parse import urlparse
        urls = self.url_input.toPlainText().strip().splitlines()
        urls = [u.strip() for u in urls if u.strip()]
        # Validate URLs: only http/https and well-formed
        valid_urls = []
        for u in urls:
            parsed = urlparse(u)
            if parsed.scheme in ("http", "https") and parsed.netloc:
                valid_urls.append(u)
            else:
                self.log_warning(f"Invalid URL skipped: {u}")
        if not valid_urls:
            self.log("Please enter at least one valid URL (http/https).")
            return
        urls = valid_urls
        output_folder = Path(self.save_path_field.text().strip())
        if not output_folder:
            self.log("Please select a save location.")
            return
        output_folder.mkdir(parents=True, exist_ok=True)
        auto_merge = self.auto_merge_checkbox.isChecked()
        # Always log number of images found (no setting)
        # Disable buttons during download
        self.download_button.setEnabled(False)
        self.merge_button.setEnabled(False)
        self.volume_button.setEnabled(False)
        # self.pause_button.setEnabled(True)  # Removed: button does not exist
        # self.resume_button.setEnabled(False)  # Removed: button does not exist
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        # Populate queue list
        self.queue_list.clear()
        self.queue = collections.OrderedDict()
        for url in urls:
            class QueueItemWidget(QWidget):
                def __init__(self, url, status="Queued"):
                    super().__init__()
                    self.url = url
                    self.status_label = QLabel(f"{status}: {url}")
                    self.progress = QProgressBar()
                    self.progress.setMinimum(0)
                    self.progress.setMaximum(100)
                    self.progress.setValue(0)
                    self.progress.setFixedWidth(120)
                    layout = QHBoxLayout()
                    layout.addWidget(self.status_label)
                    layout.addWidget(self.progress)
                    layout.setContentsMargins(0, 0, 0, 0)
                    self.setLayout(layout)
            widget = QueueItemWidget(url)
            item = QListWidgetItem()
            item.setSizeHint(widget.sizeHint())
            # Store URL and status in item data
            item.setData(256, url)  # Qt.UserRole = 256
            item.setData(257, "Queued")  # Custom role for status
            self.queue_list.addItem(item)
            self.queue_list.setItemWidget(item, widget)
            self.queue[url] = {'status': 'Queued', 'thread': None, 'widget': widget, 'item': item}
        # Double-click to retry failed
        self.queue_list.itemDoubleClicked.connect(self.retry_failed_download)
        # Right-click context menu for pause/resume
        self.queue_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.queue_list.customContextMenuRequested.connect(self.show_queue_context_menu)
        # Start a thread for each URL
        use_selenium = self.selenium_checkbox.isChecked()
        selenium_driver_path = self.selenium_driver_path_field.text().strip()
        headless_mode = self.headless_checkbox.isChecked()
        auto_merge = self.auto_merge_checkbox.isChecked()
        output_folder = str(output_folder)
        self.url_threads = {}
        for url in urls:
            thread = DownloadThread([url], output_folder, auto_merge, 1, use_selenium, selenium_driver_path, headless_mode, True)
            thread.log_signal.connect(self.log)
            thread.progress_signal.connect(self.update_progress)
            thread.finished_signal.connect(self.download_finished)
            thread.status_signal = self.update_queue_status
            thread.url_progress_signal.connect(self.update_url_progress)
            # Connect selenium error signal to dialog (only once)
            if not self._connect_selenium_error_signal:
                thread.selenium_error_signal.connect(self.show_critical_selenium_error_dialog)
                self._connect_selenium_error_signal = True
            self.url_threads[url] = thread
            thread.start()

    def show_critical_selenium_error_dialog(self, message):
        QMessageBox.critical(self, "Selenium Error", message)

    def update_url_progress(self, url, value, maximum):
        if url in self.queue:
            widget = self.queue[url]['widget']
            widget.progress.setMaximum(maximum)
            widget.progress.setValue(value)

    def show_queue_context_menu(self, pos):
        menu = QMenu()
        item = self.queue_list.itemAt(pos)
        if not item:
            return
        url = item.data(256)
        status = item.data(257)
        # Robustness: check if url is still in self.queue and item is still in the widget
        if url not in self.queue:
            return
        # Also check that the item is still in the list widget
        found = False
        for i in range(self.queue_list.count()):
            if self.queue_list.item(i) is item:
                found = True
                break
        if not found:
            return
        menu = QMenu()
        if status in ("Downloading", "Queued"):
            pause_action = menu.addAction("Pause")
        if status == "Paused":
            resume_action = menu.addAction("Resume")
        remove_action = menu.addAction("Remove/Cancel")
        action = menu.exec(self.queue_list.mapToGlobal(pos))
        if action:
            if action.text() == "Pause":
                self.pause_url_download(url)
            elif action.text() == "Resume":
                self.resume_url_download(url)
            elif action.text() == "Remove/Cancel":
                self.remove_url_from_queue(url)

    def remove_url_from_queue(self, url):
        # Cancel thread if running
        if hasattr(self, 'url_threads') and url in self.url_threads:
            thread = self.url_threads[url]
            if thread.isRunning():
                # Try to stop the thread safely
                if hasattr(thread, 'stop'):
                    thread.stop()
            del self.url_threads[url]
        # Remove from queue UI robustly
        if url in self.queue:
            item = self.queue[url]['item']
            row = self.queue_list.row(item)
            self.queue_list.takeItem(row)
            del self.queue[url]

    def pause_url_download(self, url):
        if url in self.url_threads:
            thread = self.url_threads[url]
            if hasattr(thread, 'pause'):
                thread.pause()
            self.update_queue_status(url, "Paused")

    def resume_url_download(self, url):
        if url in self.url_threads:
            thread = self.url_threads[url]
            if hasattr(thread, 'resume'):
                thread.resume()
            self.update_queue_status(url, "Downloading")

    def update_queue_status(self, url, status):
        # status: 'Queued', 'Downloading', 'Completed', 'Failed', 'Skipped'
        if url in self.queue:
            item = self.queue[url]['item']
            widget = self.queue[url]['widget']
            item.setData(257, status)
            widget.status_label.setText(f"{status}: {url}")
            if status == 'Completed':
                item.setForeground(Qt.GlobalColor.darkGreen)
            elif status == 'Failed':
                item.setForeground(Qt.GlobalColor.red)
            elif status == 'Downloading':
                item.setForeground(Qt.GlobalColor.blue)
            elif status == 'Skipped':
                item.setForeground(Qt.GlobalColor.darkYellow)
            else:
                item.setForeground(Qt.GlobalColor.black)
            self.queue[url]['status'] = status

    def retry_failed_download(self, item):
        text = item.text()
        if text.startswith("Failed: "):
            url = text[len("Failed: "):]
            # Re-queue and restart download for this URL only
            item.setText(f"Queued: {url}")
            item.setForeground(Qt.GlobalColor.black)
            output_folder = Path(self.save_path_field.text().strip())
            auto_merge = self.auto_merge_checkbox.isChecked()
            concurrency = 1  # Only one for retry
            use_selenium = self.selenium_checkbox.isChecked()
            selenium_driver_path = self.selenium_driver_path_field.text().strip()
            headless_mode = self.headless_checkbox.isChecked()
            # Start a new thread for this single URL
            thread = DownloadThread([url], str(output_folder), auto_merge, concurrency, use_selenium, selenium_driver_path, headless_mode)
            thread.log_signal.connect(self.log)
            thread.progress_signal.connect(self.update_progress)
            thread.finished_signal.connect(self.download_finished)
            thread.status_signal = self.update_queue_status
            thread.start()

    def _get_queue_state_path(self):
        home = Path.home()
        return home / ".manga_downloader_queue.json"

    def save_queue_state(self):
        # Save URLs and statuses using self.queue
        if hasattr(self, 'queue'):
            queue = []
            for url, entry in self.queue.items():
                # entry['item'] is a QListWidgetItem, entry['widget'] is the widget
                item = entry.get('item')
                status = entry.get('status', 'Queued')
                if item is not None:
                    # Try to get status from item text if possible
                    text = item.text() if hasattr(item, 'text') else ''
                    if ": " in text:
                        status = text.split(": ", 1)[0]
                queue.append({"url": url, "status": status})
            try:
                with open(self._get_queue_state_path(), "w", encoding="utf-8") as f:
                    json.dump(queue, f)
            except Exception:
                pass

    def restore_queue_state(self):
        try:
            path = self._get_queue_state_path()
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    queue = json.load(f)
                self.queue_list.clear()
                self.queue = collections.OrderedDict()
                for entry in queue:
                    from PySide6.QtWidgets import QListWidgetItem, QWidget, QHBoxLayout, QLabel, QProgressBar
                    # Recreate the custom widget as in download_images
                    class QueueItemWidget(QWidget):
                        def __init__(self, url, status="Queued"):
                            super().__init__()
                            self.url = url
                            self.status_label = QLabel(f"{status}: {url}")
                            self.progress = QProgressBar()
                            self.progress.setMinimum(0)
                            self.progress.setMaximum(100)
                            self.progress.setValue(0)
                            self.progress.setFixedWidth(120)
                            layout = QHBoxLayout()
                            layout.addWidget(self.status_label)
                            layout.addWidget(self.progress)
                            layout.setContentsMargins(0, 0, 0, 0)
                            self.setLayout(layout)
                    widget = QueueItemWidget(entry['url'], entry['status'])
                    item = QListWidgetItem()
                    item.setSizeHint(widget.sizeHint())
                    self.queue_list.addItem(item)
                    self.queue_list.setItemWidget(item, widget)
                    self.queue[entry['url']] = {'status': entry['status'], 'item': item, 'widget': widget, 'thread': None}
        except Exception:
            pass

    def _on_close_event(self, event):
        self.save_queue_state()
        if hasattr(self, '_orig_closeEvent'):
            self._orig_closeEvent(event)

    def update_progress(self, value, maximum):
        self.progress_bar.setMaximum(maximum)
        self.progress_bar.setValue(value)

    def download_finished(self):
        self.download_button.setEnabled(True)
        self.merge_button.setEnabled(True)
        self.volume_button.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.log("Image download process finished.")

    # (Global pause_download and resume_download methods removed)

    def pdf_log(self, message, level="info"):
        color = {
            "info": "#222",
            "success": "#228B22",
            "warning": "#FF8C00",
            "error": "#B22222"
        }.get(level, "#222")
        html = f'<span style="color:{color}">{message}</span>'
        if hasattr(self, 'pdf_status_box'):
            self.pdf_status_box.append(html)
            self.pdf_status_box.verticalScrollBar().setValue(self.pdf_status_box.verticalScrollBar().maximum())
        self.log(message, level)

    def merge_to_pdf(self):
        parent_folder = Path(getattr(self, 'merge_parent_folder', self.save_path_field.text().strip()))
        if not parent_folder or not parent_folder.is_dir():
            self.pdf_log("Please select a valid parent folder.", level="warning")
            return
        # Use selected folder names if set, otherwise all subfolders
        selected_names = getattr(self, 'selected_merge_folder_names', None)
        if selected_names:
            subfolders = [parent_folder / name for name in selected_names if (parent_folder / name).is_dir()]
        else:
            subfolders = [f for f in parent_folder.iterdir() if f.is_dir()]
        if not subfolders:
            self.pdf_log("No subfolders found to merge from.", level="warning")
            return
        last_pdf = None
        mode = self.merge_mode_combo.currentText() if hasattr(self, 'merge_mode_combo') else "Merge Images"
        if mode == "Merge Images":
            for folder in subfolders:
                image_files = sorted(folder.glob('*'))
                image_files = [f for f in image_files if f.suffix.lower() in ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp')]
                if not image_files:
                    self.pdf_log(f"No images found in {folder}.", level="warning")
                    continue
                images = []
                for img_path in image_files:
                    try:
                        img = Image.open(str(img_path))
                        if img.mode != 'RGB':
                            img = img.convert('RGB')
                        images.append(img)
                    except Exception as e:
                        self.pdf_log(f"Failed to open {img_path}: {e}", level="error")
                if images:
                    pdf_path = folder / (folder.name + '.pdf')
                    try:
                        images[0].save(str(pdf_path), save_all=True, append_images=images[1:])
                        self.pdf_log(f"PDF created: {pdf_path}", level="success")
                        last_pdf = str(pdf_path)
                    except Exception as e:
                        self.pdf_log(f"Failed to create PDF in {folder}: {e}", level="error")
                else:
                    self.pdf_log(f"No valid images to merge in {folder}.", level="warning")
        elif mode == "Merge PDFs":
            for folder in subfolders:
                pdf_files = sorted(folder.glob('*.pdf'))
                if not pdf_files:
                    self.pdf_log(f"No PDFs found in {folder}.", level="warning")
                    continue
                if pypdf is None:
                    self.pdf_log("pypdf or PyPDF2 is required to merge PDFs.", level="error")
                    return
                merger = pypdf.PdfWriter()
                for pdf_path in pdf_files:
                    try:
                        reader = pypdf.PdfReader(str(pdf_path))
                        for page in reader.pages:
                            merger.add_page(page)
                    except Exception as e:
                        self.pdf_log(f"Failed to read {pdf_path}: {e}", level="error")
                merged_pdf_path = folder / (folder.name + '_merged.pdf')
                try:
                    with open(merged_pdf_path, "wb") as f:
                        merger.write(f)
                    self.pdf_log(f"Merged PDF created: {merged_pdf_path}", level="success")
                    last_pdf = str(merged_pdf_path)
                except Exception as e:
                    self.pdf_log(f"Failed to create merged PDF in {folder}: {e}", level="error")
        # Show open PDF button if a PDF was created
        if last_pdf:
            self.last_pdf_path = last_pdf
            self.open_pdf_button.setVisible(True)
        else:
            self.open_pdf_button.setVisible(False)
        # Do not clear selected folders after merge; keep selection persistent

    def select_parent_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Parent Folder for Merging", str(getattr(self, 'merge_parent_folder', self.save_path_field.text())))
        if folder:
            self.merge_parent_folder = folder
            self.pdf_log(f"Selected parent folder: {folder}", level="info")
        else:
            self.pdf_log("No parent folder selected.", level="warning")

    def open_select_folders_dialog(self):
    # PySide6 widgets already imported at module top
        parent_folder = Path(getattr(self, 'merge_parent_folder', self.save_path_field.text().strip()))
        if not parent_folder or not parent_folder.is_dir():
            QMessageBox.warning(self, "Invalid Folder", "Please select a valid parent folder first.")
            return
        subfolders = [f for f in parent_folder.iterdir() if f.is_dir()]
        if not subfolders:
            QMessageBox.warning(self, "No Subfolders", "No subfolders found to select.")
            return
        class FolderSelectDialog(QDialog):
            def __init__(self, subfolders, selected_names=None, parent=None):
                super().__init__(parent)
                self.setWindowTitle("Select Folders to Merge")
                self.setMinimumWidth(400)
                layout = QVBoxLayout()
                self.list_widget = QListWidget()
                self.list_widget.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
                # PySide6: use Qt.Unchecked and Qt.Checked only
                unchecked = Qt.Unchecked
                checked = Qt.Checked
                for folder in subfolders:
                    item = QListWidgetItem(str(folder.name))
                    if selected_names and str(folder.name) in selected_names:
                        item.setCheckState(checked)
                    else:
                        item.setCheckState(unchecked)
                    self.list_widget.addItem(item)
                layout.addWidget(self.list_widget)
                btn_layout = QHBoxLayout()
                select_all_btn = QPushButton("Select All")
                deselect_all_btn = QPushButton("Deselect All")
                ok_btn = QPushButton("OK")
                cancel_btn = QPushButton("Cancel")
                btn_layout.addWidget(select_all_btn)
                btn_layout.addWidget(deselect_all_btn)
                btn_layout.addWidget(ok_btn)
                btn_layout.addWidget(cancel_btn)
                layout.addLayout(btn_layout)
                self.setLayout(layout)
                ok_btn.clicked.connect(self.accept)
                cancel_btn.clicked.connect(self.reject)
                # Cross-Qt: get checked/unchecked enums
                try:
                    checked = Qt.CheckState.Checked
                    unchecked = Qt.CheckState.Unchecked
                except AttributeError:
                    checked = Qt.Checked
                    unchecked = Qt.Unchecked
                def select_all():
                    for i in range(self.list_widget.count()):
                        self.list_widget.item(i).setCheckState(checked)
                def deselect_all():
                    for i in range(self.list_widget.count()):
                        self.list_widget.item(i).setCheckState(unchecked)
                select_all_btn.clicked.connect(select_all)
                deselect_all_btn.clicked.connect(deselect_all)
            def get_selected_folders(self):
                # Only include folders where checkState is exactly Checked
                checked = Qt.Checked
                return [subfolders[i] for i in range(self.list_widget.count()) if self.list_widget.item(i).checkState() == checked]
            def get_selected_names(self):
                checked = Qt.Checked
                return [str(subfolders[i].name) for i in range(self.list_widget.count()) if self.list_widget.item(i).checkState() == checked]
        # Remember previous selection by folder name
        selected_names = getattr(self, 'selected_merge_folder_names', None)
        dlg = FolderSelectDialog(subfolders, selected_names, self)
        if dlg.exec():
            selected_names = dlg.get_selected_names()
            if selected_names:
                self.selected_merge_folder_names = selected_names
                self.pdf_log(f"Selected {len(selected_names)} folder(s) for merging.", level="info")
            else:
                if hasattr(self, 'selected_merge_folder_names'):
                    del self.selected_merge_folder_names
                self.pdf_log("No folders selected. All subfolders will be used.", level="warning")
        else:
            self.pdf_log("Folder selection cancelled.", level="info")

    def compile_volume_pdf(self):
        output_folder = Path(self.save_path_field.text().strip())
        if not output_folder or not output_folder.is_dir():
            self.pdf_log("Please select a valid save location.", level="warning")
            return
        # For simplicity, use all subfolders (since QFileDialog.getExistingDirectory does not support multi-select in PyQt6)
        subfolders = [f for f in output_folder.iterdir() if f.is_dir()]
        if not subfolders:
            self.pdf_log("No chapter folders found.", level="warning")
            return
        # Ask for output PDF name
        pdf_path, _ = QFileDialog.getSaveFileName(self, "Save Volume PDF As", str(output_folder), "PDF Files (*.pdf)")
        if not pdf_path:
            self.pdf_log("No output file selected.", level="warning")
            return
        # Start worker thread
        self.volume_thread = VolumePDFThread([str(f) for f in subfolders], pdf_path)
        self.volume_thread.log_signal.connect(lambda msg: self.pdf_log(msg))
        self.volume_thread.finished_signal.connect(lambda: self.pdf_log("Volume PDF process finished.", level="success"))
        self.volume_thread.start()

    def open_edit_pdf_dialog(self):
    # PySide6 widgets already imported at module top
        import os
        if pypdf is None:
            QMessageBox.warning(self, "Missing Dependency", "pypdf or PyPDF2 is required for PDF editing.")
            return
        class EditPDFDialog(QDialog):
            def __init__(self, parent=None):
                super().__init__(parent)
                self.setWindowTitle("Edit PDF")
                self.setMinimumWidth(600)
                self.layout = QVBoxLayout()
                preview_layout = QHBoxLayout()
                self.list_widget = QListWidget()
                self.list_widget.setMinimumWidth(120)
                preview_layout.addWidget(self.list_widget)
                # PDF page preview
                # PySide6 QLabel already imported at module top
                self.preview_label = QLabel("Select a page to preview")
                self.preview_label.setMinimumSize(300, 400)
                # Set alignment cross-Qt
                self.preview_label.setAlignment(Qt.AlignCenter)
                preview_layout.addWidget(self.preview_label)
                self.layout.addLayout(preview_layout)
                btn_layout = QHBoxLayout()
                self.up_btn = QPushButton("Move Up")
                self.down_btn = QPushButton("Move Down")
                self.delete_btn = QPushButton("Delete Page")
                self.save_btn = QPushButton("Save As...")
                btn_layout.addWidget(self.up_btn)
                btn_layout.addWidget(self.down_btn)
                btn_layout.addWidget(self.delete_btn)
                btn_layout.addWidget(self.save_btn)
                self.layout.addLayout(btn_layout)
                self.setLayout(self.layout)
                self.up_btn.clicked.connect(self.move_up)
                self.down_btn.clicked.connect(self.move_down)
                self.delete_btn.clicked.connect(self.delete_page)
                self.save_btn.clicked.connect(self.save_pdf)
                self.list_widget.currentRowChanged.connect(self.update_preview)
                self.pdf = None
                self.page_order = []
                self.pdf_path = None
                self.load_pdf()
            def load_pdf(self):
                file_path, _ = QFileDialog.getOpenFileName(self, "Open PDF to Edit", os.getcwd(), "PDF Files (*.pdf)")
                if not file_path:
                    self.reject()
                    return
                try:
                    self.pdf = pypdf.PdfReader(file_path)
                    self.page_order = list(range(len(self.pdf.pages)))
                    self.list_widget.clear()
                    self.pdf_path = file_path
                    for i in self.page_order:
                        self.list_widget.addItem(f"Page {i+1}")
                except Exception as e:
                    import traceback
                    tb = traceback.format_exc()
                    # Show error in a copyable dialog
                    self.show_copyable_error("Failed to open PDF", f"{e}\n\nTraceback:\n{tb}")
                    self.reject()
                self.preview_label.setAlignment(Qt.AlignCenter)
                self.setLayout(self.layout)
            def move_up(self):
                row = self.list_widget.currentRow()
                if row > 0:
                    self.page_order[row-1], self.page_order[row] = self.page_order[row], self.page_order[row-1]
                    self.refresh_list(row-1)
            def move_down(self):
                row = self.list_widget.currentRow()
                if row < len(self.page_order)-1 and row != -1:
                    self.page_order[row+1], self.page_order[row] = self.page_order[row], self.page_order[row+1]
                    self.refresh_list(row+1)
            def delete_page(self):
                row = self.list_widget.currentRow()
                if row != -1:
                    del self.page_order[row]
                    self.refresh_list(row)
            def refresh_list(self, select_row=0):
                self.list_widget.clear()
                for i in self.page_order:
                    self.list_widget.addItem(f"Page {i+1}")
                self.list_widget.setCurrentRow(select_row)
                self.update_preview(select_row)

            def update_preview(self, row):
                try:
                    from pdf2image import convert_from_path
                except ImportError:
                    self.preview_label.setText(
                        "PDF preview not available.\n" +
                        "Missing dependency: <b>pdf2image</b>.<br>" +
                        "Install with: <code>pip install pdf2image</code><br>"
                        "Also ensure poppler is installed and on your PATH."
                    )
                    return
                # Use user-selected poppler path if available
                poppler_path = None
                if hasattr(self.parent(), 'poppler_path_field'):
                    poppler_path_val = self.parent().poppler_path_field.text().strip()
                    if poppler_path_val:
                        poppler_path = os.path.dirname(poppler_path_val)
                if not poppler_path:
                    import shutil
                    poppler_bin = shutil.which("pdftoppm.exe") if sys.platform.startswith('win') else shutil.which("pdftoppm")
                    if not poppler_bin:
                        self.preview_label.setText(
                            "PDF preview not available.\n" +
                            "Missing dependency: <b>poppler</b>.<br>"
                            "See instructions in the Settings tab or install poppler and add it to your PATH."
                        )
                        return
                    poppler_path = os.path.dirname(poppler_bin)
                if self.pdf_path is None or row < 0 or row >= len(self.page_order):
                    self.preview_label.setText("Select a page to preview")
                    return
                try:
                    # Debug print: show file path and page number
                    print(f"[DEBUG] PDF path: {self.pdf_path}")
                    page_num = self.page_order[row] + 1
                    print(f"[DEBUG] Requesting page: {page_num}")
                    images = convert_from_path(self.pdf_path, first_page=page_num, last_page=page_num, size=(300, 400), dpi=300, poppler_path=poppler_path)
                    if images:
                        from PySide6.QtGui import QPixmap, QImage
                        img = images[0]
                        img = img.convert("RGB")
                        data = img.tobytes("raw", "RGB")
                        qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGB888)
                        pixmap = QPixmap.fromImage(qimg)
                        aspect = Qt.KeepAspectRatio
                        transform = Qt.SmoothTransformation
                        self.preview_label.setPixmap(pixmap.scaled(self.preview_label.size(), aspect, transform))
                    else:
                        self.preview_label.setText("No preview available")
                except Exception as e:
                    print(f"[DEBUG] Exception in update_preview: {e}")
                    self.preview_label.setText(
                        "PDF preview not available (poppler not installed or error occurred).<br>"
                        "See instructions in the Settings tab."
                    )
                    # Do not show error dialog, just show message in preview area
            def save_pdf(self):
                if not self.pdf:
                    return
                out_path, _ = QFileDialog.getSaveFileName(self, "Save Edited PDF As", os.getcwd(), "PDF Files (*.pdf)")
                if not out_path:
                    return
                writer = pypdf.PdfWriter()
                for i in self.page_order:
                    writer.add_page(self.pdf.pages[i])
                with open(out_path, "wb") as f:
                    writer.write(f)
                QMessageBox.information(self, "Saved", f"PDF saved as {out_path}")
                self.accept()
        dlg = EditPDFDialog(self)
        dlg.exec()

import threading

class DownloadThread(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal()
    url_progress_signal = pyqtSignal(str, int, int)  # url, value, max
    selenium_error_signal = pyqtSignal(str)

    def __init__(self, urls, output_folder, auto_merge, concurrency, use_selenium=False, selenium_driver_path="", headless_mode=True, log_num_images_found=True):
        super().__init__()
        self.urls = urls
        self.output_folder = output_folder
        self.auto_merge = auto_merge
        self.concurrency = concurrency
        self.use_selenium = use_selenium
        self.selenium_driver_path = selenium_driver_path
        self.headless_mode = headless_mode
        self.log_num_images_found = True  # Always log
        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused by default
        self._stop_event = threading.Event()
        self._stop_event.clear()

    def stop(self):
        self._stop_event.set()
        self._pause_event.set()  # Unpause if paused, so thread can exit

    def pause(self):
        self._pause_event.clear()

    def resume(self):
        self._pause_event.set()

    def run(self):
        import re
        total_downloaded = 0
        driver = None
        if self.use_selenium and webdriver is not None:
            chrome_options = ChromeOptions()
            if self.headless_mode:
                chrome_options.add_argument('--headless')
            chrome_options.add_argument('--disable-gpu')
            driver_path = self.selenium_driver_path if self.selenium_driver_path else None
            from selenium.webdriver.chrome.service import Service as ChromeService
            try:
                if driver_path:
                    driver = webdriver.Chrome(service=ChromeService(driver_path), options=chrome_options)
                else:
                    driver = webdriver.Chrome(options=chrome_options)
            except Exception as e:
                error_msg = f"Failed to initialize Selenium driver: {e}"
                self.log_signal.emit(error_msg)
                self.selenium_error_signal.emit(error_msg)
                driver = None
        try:
            for url in self.urls:
                # Check for stop event
                if self._stop_event.is_set():
                    self.log_signal.emit("Download stopped by user.")
                    break
                # Per-URL pause support
                if hasattr(self, '_pause_event'):
                    while not self._pause_event.is_set():
                        self.msleep(100)
                self.log_signal.emit(f"\nProcessing: {url}")
                parsed = urlparse(url)
                path_parts = [p for p in parsed.path.split('/') if p]
                folder_name = parsed.netloc
                chapter_pattern = re.compile(r'(vol\d+[-_ ]*)?(ch|chapter)[-_ ]*(\d+)', re.IGNORECASE)
                chapter_name = None
                for part in reversed(path_parts):
                    match = chapter_pattern.search(part)
                    if match:
                        chapter_name = match.group(0).replace('_', '-').replace(' ', '-')
                        break
                if not chapter_name and path_parts:
                    chapter_name = path_parts[-1]
                if chapter_name:
                    folder_name = f"{parsed.netloc}_{chapter_name}"
                folder_name = folder_name.replace(':', '_').replace('?', '_').replace('&', '_').replace('=', '_')
                url_folder = os.path.join(self.output_folder, folder_name)
                os.makedirs(url_folder, exist_ok=True)
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"}
                try:
                    response = requests.get(url, headers=headers)
                    response.raise_for_status()
                except Exception as e:
                    self.log_signal.emit(f"Failed to fetch page: {e}")
                    continue
                # Use plugin system for image extraction
                image_urls = None
                for plugin in getattr(self.parent(), 'plugins', []):
                    if plugin.can_handle(url):
                        try:
                            image_urls = plugin.get_image_urls(url)
                            break
                        except Exception as e:
                            self.log_signal.emit(f"Plugin error for {url}: {e}")
                if image_urls is None:
                    # fallback: try to extract all <img> tags
                    try:
                        if self.use_selenium and webdriver is not None and driver is not None:
                            import time
                            from selenium.common.exceptions import TimeoutException, WebDriverException
                            from selenium.webdriver.support.ui import WebDriverWait
                            from selenium.webdriver.support import expected_conditions as EC
                            max_retries = 3
                            for attempt in range(1, max_retries + 1):
                                try:
                                    driver.get(url)
                                    # Scroll to bottom to trigger lazy loading (increase attempts)
                                    last_height = driver.execute_script("return document.body.scrollHeight")
                                    for _ in range(10):
                                        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                                        time.sleep(1.5)
                                        new_height = driver.execute_script("return document.body.scrollHeight")
                                        if new_height == last_height:
                                            break
                                        last_height = new_height
                                    # Wait for images to load
                                    try:
                                        WebDriverWait(driver, 15).until(
                                            EC.presence_of_all_elements_located((By.TAG_NAME, "img"))
                                        )
                                    except Exception:
                                        pass
                                    img_elements = driver.find_elements(By.TAG_NAME, "img")
                                    image_urls = [img.get_attribute("src") for img in img_elements if img.get_attribute("src")]
                                    break  # Success, exit retry loop
                                except (TimeoutException, WebDriverException) as e:
                                    if attempt == max_retries:
                                        self.log_signal.emit(f"Selenium error for {url}: {e}")
                                        image_urls = []
                                    else:
                                        self.log_signal.emit(f"Selenium timeout/error for {url}, retrying ({attempt}/{max_retries})...")
                                        time.sleep(2)
                        else:
                            response = requests.get(url)
                            response.raise_for_status()
                            soup = BeautifulSoup(response.text, "html.parser")
                            img_tags = soup.find_all("img")
                            image_urls = [urljoin(url, img.get("src")) for img in img_tags if img.get("src")]
                    except Exception as e:
                        self.log_signal.emit(f"Failed to fetch page: {e}")
                        continue
                downloaded = 0
                img_tags = []
                # Convert image_urls to dummy img_tag-like objects for compatibility
                class DummyImg:
                    def __init__(self, src):
                        self._src = src
                    def get(self, key):
                        return self._src if key == "src" else None
                img_tags = [DummyImg(src) for src in image_urls]
                # Log number of images found if enabled
                if self.log_num_images_found:
                    self.log_signal.emit(f"Number of images found for {url}: {len(img_tags)}")
                from concurrent.futures import ThreadPoolExecutor, as_completed
                import re
                def normalize_filename(name):
                    # Remove or replace problematic characters
                    name = re.sub(r'[\\/:*?"<>|]', '_', name)
                    name = re.sub(r'\s+', '_', name)
                    return name

                def download_image(img, session, headers, retries=3, timeout=10):
                    import traceback
                    # Early exit if stop requested
                    if self._stop_event.is_set():
                        return False, None, None
                    img_url = img.get("src")
                    if not img_url:
                        return False, None, None
                    img_url_full = urljoin(url, img_url)
                    img_name = os.path.basename(urlparse(img_url_full).path)
                    if not img_name:
                        return False, img_url_full, None
                    img_name = normalize_filename(img_name)
                    # Check for extension
                    root, ext = os.path.splitext(img_name)
                    # Ensure unique filename to avoid overwrites
                    img_path = os.path.join(url_folder, img_name)
                    base_img_name = root
                    counter = 1
                    while os.path.exists(img_path):
                        # Append _1, _2, etc. before extension
                        img_name = f"{base_img_name}_{counter}{ext}"
                        img_path = os.path.join(url_folder, img_name)
                        counter += 1
                    last_exception = None
                    last_trace = None
                    for attempt in range(1, retries + 1):
                        # Early exit if stop requested
                        if self._stop_event.is_set():
                            return False, None, None
                        try:
                            img_data = session.get(img_url_full, headers=headers, timeout=timeout)
                            # Check for permanent errors (404, 410)
                            if img_data.status_code in (404, 410):
                                return False, img_url_full, f"HTTP {img_data.status_code} (permanent error, not retried)"
                            img_data.raise_for_status()
                            # If no extension, use Content-Type to determine extension
                            if not ext:
                                content_type = img_data.headers.get('Content-Type', '').lower()
                                ext_map = {
                                    'image/jpeg': '.jpg',
                                    'image/jpg': '.jpg',
                                    'image/png': '.png',
                                    'image/gif': '.gif',
                                    'image/bmp': '.bmp',
                                    'image/webp': '.webp',
                                }
                                new_ext = ext_map.get(content_type, '')
                                if new_ext:
                                    img_name = root + new_ext
                                    img_path = os.path.join(url_folder, img_name)
                            with open(img_path, "wb") as f:
                                f.write(img_data.content)
                            return True, img_name, None
                        except requests.HTTPError as e:
                            # Permanent error: do not retry on 4xx except 408 (timeout)
                            if hasattr(e.response, 'status_code') and e.response is not None:
                                code = e.response.status_code
                                if code in (404, 410) or (400 <= code < 500 and code != 408):
                                    return False, img_url_full, f"HTTP {code} (permanent error, not retried)"
                            last_exception = e
                            last_trace = traceback.format_exc()
                        except (requests.ConnectionError, requests.Timeout) as e:
                            # Transient error: retry
                            last_exception = e
                            last_trace = traceback.format_exc()
                        except Exception as e:
                            last_exception = e
                            last_trace = traceback.format_exc()
                    return False, img_url_full, f"{last_exception}\n{last_trace}" if last_exception else None

                downloaded = 0
                total_imgs = len(img_tags)
                completed_imgs = 0
                with requests.Session() as session:
                    with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
                        futures = {executor.submit(download_image, img, session, headers): img for img in img_tags}
                        last_progress_emit = 0
                        last_url_progress_emit = 0
                        progress_emit_interval = max(1, total_imgs // 100)  # Emit at most 100 times
                        for future in as_completed(futures):
                            # Pause support
                            while not self._pause_event.is_set():
                                self.msleep(100)
                            # Early exit if stop requested
                            if self._stop_event.is_set():
                                break
                            success, name_or_url, err = future.result()
                            completed_imgs += 1
                            # Throttle progress signal emissions
                            if completed_imgs - last_progress_emit >= progress_emit_interval or completed_imgs == total_imgs:
                                self.progress_signal.emit(completed_imgs, total_imgs)
                                last_progress_emit = completed_imgs
                            if completed_imgs - last_url_progress_emit >= progress_emit_interval or completed_imgs == total_imgs:
                                self.url_progress_signal.emit(url, completed_imgs, total_imgs)
                                last_url_progress_emit = completed_imgs
                            # Log every successful download, skip, or failure
                            if success is True:
                                self.log_signal.emit(f"Downloaded: {name_or_url}")
                                downloaded += 1
                            elif success == 'skipped':
                                self.log_signal.emit(f"Skipped existing: {name_or_url}")
                            elif not success and name_or_url:
                                self.log_signal.emit(f"Failed to download {name_or_url}: {err}")
                        # If stop requested, cancel remaining futures
                        if self._stop_event.is_set():
                            for fut in futures:
                                fut.cancel()
                            break
                self.log_signal.emit(f"Images downloaded from this page: {downloaded}")
                total_downloaded += downloaded
                # Auto-merge to PDF if enabled
                if self.auto_merge and downloaded > 0:
                    self._merge_images_to_pdf(url_folder)
        finally:
            if driver is not None:
                driver.quit()
        self.log_signal.emit(f"\nTotal images downloaded from all URLs: {total_downloaded}")
        self.finished_signal.emit()

    def _merge_images_to_pdf(self, folder):
        import glob
        import re
        from PIL import Image
        def natural_key(s):
            return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', os.path.basename(s))]
        image_files = glob.glob(os.path.join(folder, '*'))
        image_files = [f for f in image_files if f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp'))]
        image_files.sort(key=natural_key)
        if not image_files:
            self.log_signal.emit(f"[Auto-Merge] No images found in {folder}.")
            return
        pdf_path = os.path.join(folder, os.path.basename(folder) + '.pdf')
        valid_images = []
        max_w, max_h = 0, 0
        # First pass: determine max size and filter valid images
        for img_path in image_files:
            try:
                img = Image.open(img_path)
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                max_w = max(max_w, img.width)
                max_h = max(max_h, img.height)
                valid_images.append(img_path)
            except Exception as e:
                self.log_signal.emit(f"[Auto-Merge] Failed to open {img_path}: {e}")
        if not valid_images:
            self.log_signal.emit(f"[Auto-Merge] No valid images to merge in {folder}.")
            return
        try:
            # Streaming approach: write images one by one
            first_img = None
            padded_paths = []
            from tempfile import NamedTemporaryFile
            for idx, img_path in enumerate(valid_images):
                try:
                    img = Image.open(img_path)
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    new_img = Image.new('RGB', (max_w, max_h), (255, 255, 255))
                    offset = ((max_w - img.width) // 2, (max_h - img.height) // 2)
                    new_img.paste(img, offset)
                    # Save each padded image as a temporary file
                    temp_file = NamedTemporaryFile(delete=False, suffix='.jpg')
                    new_img.save(temp_file.name, format='JPEG')
                    padded_paths.append(temp_file.name)
                    temp_file.close()
                    if first_img is None:
                        first_img = new_img
                except Exception as e:
                    self.log_signal.emit(f"[Auto-Merge] Failed to process {img_path}: {e}")
            if not padded_paths:
                self.log_signal.emit(f"[Auto-Merge] No valid images to merge in {folder}.")
                return
            # Save to PDF incrementally
            try:
                images_iter = (Image.open(p) for p in padded_paths)
                first = next(images_iter)
                first.save(pdf_path, save_all=True, append_images=list(images_iter))
                self.log_signal.emit(f"[Auto-Merge] PDF created: {pdf_path}")
            except Exception as e:
                self.log_signal.emit(f"[Auto-Merge] Failed to create PDF in {folder}: {e}")
            finally:
                # Clean up temp files
                for p in padded_paths:
                    try:
                        os.remove(p)
                    except Exception:
                        pass
        except Exception as e:
            self.log_signal.emit(f"[Auto-Merge] Unexpected error: {e}")

class VolumePDFThread(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, subfolders, pdf_path):
        super().__init__()
        self.subfolders = subfolders
        self.pdf_path = pdf_path

    def run(self):
        all_images = []
        for folder in sorted(self.subfolders):
            image_files = sorted(glob.glob(os.path.join(folder, '*')))
            image_files = [f for f in image_files if f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp'))]
            for img_path in image_files:
                try:
                    img = Image.open(img_path)
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    all_images.append(img)
                except Exception as e:
                    self.log_signal.emit(f"Failed to open {img_path}: {e}")
        if all_images:
            try:
                all_images[0].save(self.pdf_path, save_all=True, append_images=all_images[1:])
                self.log_signal.emit(f"Volume PDF created: {self.pdf_path}")
            except Exception as e:
                self.log_signal.emit(f"Failed to create volume PDF: {e}")
        else:
            self.log_signal.emit("No valid images to merge for volume.")
        self.finished_signal.emit()

    
def main():
    # High-DPI scaling is now handled automatically by Qt/PySide6
    app = QApplication(sys.argv)
    window = MangaDownloader()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()