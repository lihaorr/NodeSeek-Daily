"""Local Windows entry point; shared GitHub checkpoints, no stored GitHub token."""
import argparse
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime
import os
from pathlib import Path
import re
import subprocess
import time

import nodeseek_daily
from browser_actions import AccountUnconfirmed, PageBlocked, assert_account, ensure_page
from local_browser import open_profile_browser
from state_store import FileStateStore


@contextmanager
def runtime_environment(values):
    previous = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def login(profile, user_id):
    driver = open_profile_browser(profile)
    try:
        driver.get('https://www.nodeseek.com/')
        print('请在专用 Chrome 窗口自行登录 NodeSeek；完成后程序会自动确认账号。', flush=True)
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            try:
                ensure_page(driver)
                assert_account(driver, user_id)
            except AccountUnconfirmed:
                time.sleep(3)
                continue
            except PageBlocked:
                print('检测到站点安全验证或访问限制；已停止当前自动浏览器，不会刷新或重试。', flush=True)
                return 1
            print('专用浏览器账号已确认，登录会话已保存。', flush=True)
            return 0
        print('登录等待超时；未执行签到或评论。')
        return 1
    finally:
        driver.quit()


def run(argv=None):
    parser = argparse.ArgumentParser(description='当前电脑运行；必须先在专用浏览器完成登录')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--login', action='store_true')
    mode.add_argument('--search-preview', action='store_true')
    mode.add_argument('--live', action='store_true')
    parser.add_argument('--user-id', required=True)
    parser.add_argument('--repository', default='lihaorr/NodeSeek-Daily')
    parser.add_argument('--log-file', type=Path)
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[1-9]\d*', args.user_id):
        parser.error('--user-id 必须是个人主页数字 ID')
    if args.log_file:
        args.log_file.parent.mkdir(parents=True, exist_ok=True)
        with args.log_file.open('a', encoding='utf-8', buffering=1) as log:
            with redirect_stdout(log), redirect_stderr(log):
                print('\n运行时间：' + datetime.now().astimezone().isoformat())
                code = run_task(args)
                print('退出码：' + str(code))
                return code
    return run_task(args)


def run_task(args):
    directory = Path(os.environ.get('NS_LOCAL_DIR') or Path(__file__).parent / 'state' / 'local')
    try:
        with FileStateStore(directory / 'run').lock():
            profile = directory / 'chrome-profile'
            if args.login:
                return login(profile, args.user_id)
            credentials = subprocess.run(['gh', 'auth', 'token', '--hostname', 'github.com'],
                                         capture_output=True, text=True, timeout=15, check=False)
            if credentials.returncode or not credentials.stdout.strip():
                raise RuntimeError('本机 GitHub CLI 未登录，未执行账号操作')
            with runtime_environment({
                'NS_STATE_BACKEND': 'github', 'GITHUB_REPOSITORY': args.repository,
                'NS_STATE_BRANCH': 'automation-state', 'GH_TOKEN': credentials.stdout.strip(),
                'NS_PROFILE_DIR': str(profile.resolve()), 'NS_USER_ID': args.user_id,
                'NS_COOKIE': None, 'COOKIE': None, 'HEADLESS': 'false',
            }):
                return nodeseek_daily.main(['--live' if args.live else '--search-preview'])
    except FileExistsError:
        print('另一个本机任务或登录窗口正在运行；未启动第二个任务。')
        return 1
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print('本机任务停止：' + type(error).__name__ + '；请检查登录状态和本机日志。')
        return 1


if __name__ == '__main__':
    raise SystemExit(run())
