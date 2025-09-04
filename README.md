# Manga Downloader S (v1.0)

A user-friendly, cross-platform manga downloader with a graphical interface, supporting automatic image downloading, PDF merging, plugin-based site support, and robust error handling.

## Features

- Download manga chapter images from supported sites (e.g., Asura Scans)
- Automatic scrolling and dynamic image loading (Selenium-based)
- Merge downloaded images into PDFs per chapter or volume
- Plugin system for easy support of new manga sites
- Progress bar, pause/resume, and clear user feedback
- Skips already-downloaded images and normalizes filenames
- Remembers last save location and allows opening download folders
- No manual ChromeDriver setup required (uses webdriver-manager)
- Drag-and-drop URLs and text files into the input field
- Copy URLs and log output to clipboard
- Open last merged PDF directly from the app
- Control number of concurrent downloads
- Manual and auto PDF merge options
- Compile all chapters into a single volume PDF
- Supports PySide6

## Requirements

- Python 3.8+
- Google Chrome (latest recommended)
- One of: PySide6
- pip install -r requirements.txt

## Installation

1. Clone or download this repository.
2. Install dependencies:
   ```sh
   pip install -r requirements.txt
   # And install ONE binding, e.g.:
   pip install PySide6
   ```
3. Ensure Google Chrome is installed and up to date.

## Usage

1. Run the app:
   ```sh
   python manga_downloader_qt.py
   ```
2. Paste manga chapter URLs (one per line), or drag-and-drop URLs/text files.
3. Choose a save location (optional).
4. Set the number of concurrent downloads as desired.
5. Click "Download Images" to start downloading.
6. Use the "Auto-merge images to PDF after download" option for instant PDF creation.
7. Use the plugin system to add support for new sites (see `plugins/` directory).
8. Use the "Merge Downloaded Images to PDF" or "Compile Chapters to Volume PDF" for manual PDF creation.
9. Open the last merged PDF or the download folder directly from the app.

## Plugin System

- Add new site support by creating a new `*_plugin.py` file in the `plugins/` directory.
- Each plugin must implement `can_handle(url)` and `get_image_urls(url)` methods.
- See `plugins/asuracomic_plugin.py` for an example.

## Troubleshooting

- If Chrome does not open or downloads fail, ensure Chrome is installed and up to date.
- The app uses webdriver-manager to automatically manage ChromeDriver.
- For sites with dynamic/lazy-loaded images, the app scrolls the page to trigger loading.
- If you encounter issues with the GUI, try installing a 99(PySide6).

## Version

**Current version:** 1.0

## License

MIT License
