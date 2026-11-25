"""Standard Chrome using only a newly created, project-owned login profile."""
import os
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.service import Service


def open_profile_browser(directory, *, headless=False):
    profile = Path(directory).expanduser().resolve()
    marker = profile / '.nodeseek-profile'
    if profile.exists() and any(profile.iterdir()) and not marker.is_file():
        raise ValueError('必须使用新的项目专用浏览器目录，禁止使用个人浏览器配置')
    profile.mkdir(parents=True, exist_ok=True)
    marker.touch(exist_ok=True)
    options = webdriver.ChromeOptions()
    options.add_argument('--user-data-dir=' + str(profile))
    options.add_argument('--window-size=1280,900')
    if headless:
        options.add_argument('--headless=new')
    if os.environ.get('CHROME_PATH'):
        options.binary_location = os.environ['CHROME_PATH']
    service = Service(executable_path=os.environ.get('CHROMEDRIVER_PATH'))
    driver = webdriver.Chrome(options=options, service=service)
    driver.set_page_load_timeout(45)
    return driver
