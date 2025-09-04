import time
import os
from plugins.base_plugin import MangaSitePlugin
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

class AsuraComicPlugin(MangaSitePlugin):
    def can_handle(self, url: str) -> bool:
        return "asurascans.com" in url or "asuracomic.net" in url

    def get_image_urls(self, url: str) -> list:
        options = Options()
        # Do NOT add headless, so Chrome window is visible
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        chromedriver_path = ""
        try:
            with open("chromedriver_path.json", "r") as f:
                import json
                data = json.load(f)
                chromedriver_path = data.get("chromedriver_path", "")
        except Exception:
            pass
        try:
            if chromedriver_path and os.path.exists(chromedriver_path):
                driver = webdriver.Chrome(executable_path=chromedriver_path, options=options)
            else:
                driver = webdriver.Chrome(ChromeDriverManager().install(), options=options)
        except Exception as e:
            print(f"[PLUGIN ERROR] Failed to start ChromeDriver: {e}")
            return []
        driver.get(url)
        # Auto-scroll to bottom to trigger lazy loading
        last_height = driver.execute_script("return document.body.scrollHeight")
        scroll_pause = 1.0
        for _ in range(20):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(scroll_pause)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
        # Robust image extraction from live DOM
        valid_exts = (".jpg", ".jpeg", ".png", ".webp")
        image_urls = []
        for img in driver.find_elements(By.TAG_NAME, "img"):
            try:
                src = img.get_attribute("src")
                size = img.size
                if (
                    src
                    and src.lower().endswith(valid_exts)
                    and img.is_displayed()
                    and size["width"] >= 100
                    and size["height"] >= 50
                ):
                    image_urls.append(src)
            except Exception:
                continue
        driver.quit()
        return image_urls
