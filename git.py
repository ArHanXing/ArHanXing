#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
游戏存档同步工具 - 通过 Git 与 GitHub 同步本地文件夹
用法:
    python sync_saves.py push       # 将本地存档推送到 GitHub
    python sync_saves.py pull       # 从 GitHub 拉取存档到本地
    python sync_saves.py sync       # 先拉取再推送（双向同步）
"""

import os
import sys
import subprocess
import argparse
from pathlib import Path

# ========== 配置区 ==========
# 要同步的文件夹名（位于脚本所在目录下）
SAVE_FOLDER = "saves"
# Git 提交信息模板（可包含时间戳）
COMMIT_MESSAGE = "自动同步游戏存档 - {timestamp}"
# 是否在 pull 前自动提交本地更改（避免丢失未推送的本地进度）
AUTO_COMMIT_BEFORE_PULL = True
# ============================

def get_script_dir():
    """获取脚本所在目录的绝对路径"""
    return Path(__file__).resolve().parent

def get_save_path():
    """获取存档文件夹的完整路径"""
    return get_script_dir() / SAVE_FOLDER

def run_git_command(cmd, cwd, capture_output=True):
    """执行 git 命令，返回 (success, stdout, stderr)"""
    try:
        if capture_output:
            result = subprocess.run(
                cmd, cwd=cwd, shell=False,
                capture_output=True, text=True, check=False
            )
            return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
        else:
            # 实时输出模式
            subprocess.run(cmd, cwd=cwd, shell=False, check=True)
            return True, "", ""
    except subprocess.CalledProcessError as e:
        return False, "", str(e)
    except FileNotFoundError:
        return False, "", "Git 未安装或不在 PATH 中，请先安装 Git"

def is_git_repo(path):
    """检查目录是否为 Git 仓库"""
    git_dir = path / ".git"
    return git_dir.exists() and git_dir.is_dir()

def init_git_repo(path, remote_url=None):
    """初始化 Git 仓库并可选添加远程仓库"""
    if is_git_repo(path):
        print(f"[信息] 已存在 Git 仓库: {path}")
        return True

    print(f"[信息] 初始化 Git 仓库: {path}")
    success, _, err = run_git_command(["git", "init"], cwd=path)
    if not success:
        print(f"[错误] 初始化失败: {err}")
        return False

    # 创建默认 .gitignore 忽略临时文件
    gitignore_path = path / ".gitignore"
    if not gitignore_path.exists():
        with open(gitignore_path, "w") as f:
            f.write("# 游戏存档同步忽略文件\n*.tmp\n*.bak\nThumbs.db\n.DS_Store\n")
        run_git_command(["git", "add", ".gitignore"], cwd=path)

    if remote_url:
        print(f"[信息] 添加远程仓库: {remote_url}")
        run_git_command(["git", "remote", "add", "origin", remote_url], cwd=path)

    # 初次提交空仓库或已有文件
    print("[信息] 首次提交当前所有文件...")
    run_git_command(["git", "add", "."], cwd=path)
    success, _, err = run_git_command(["git", "commit", "-m", "初始化存档仓库"], cwd=path)
    if not success and "nothing to commit" not in err:
        print(f"[警告] 初次提交可能失败: {err}")
    return True

def get_current_branch(repo_path):
    """获取当前分支名"""
    success, branch, _ = run_git_command(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path
    )
    return branch if success else "main"

def commit_local_changes(repo_path, message):
    """提交所有本地更改，如果没有更改则跳过"""
    # 检查是否有更改
    success, status, _ = run_git_command(["git", "status", "--porcelain"], cwd=repo_path)
    if not success:
        return False
    if not status.strip():
        print("[信息] 没有需要提交的更改")
        return True

    # 添加所有更改
    run_git_command(["git", "add", "."], cwd=repo_path)
    # 提交
    success, _, err = run_git_command(["git", "commit", "-m", message], cwd=repo_path)
    if success:
        print("[信息] 已提交本地更改")
    else:
        print(f"[错误] 提交失败: {err}")
    return success

def pull_from_remote(repo_path, branch):
    """从远程拉取更新（使用 rebase 避免多余的合并提交）"""
    print(f"[信息] 从 origin/{branch} 拉取更新...")
    # 先 fetch 查看是否有更新
    success, _, err = run_git_command(["git", "fetch", "origin", branch], cwd=repo_path)
    if not success:
        print(f"[错误] Fetch 失败: {err}")
        return False

    # 检查是否有冲突（简单 pull 尝试）
    success, out, err = run_git_command(["git", "pull", "--rebase", "origin", branch], cwd=repo_path)
    if success:
        print("[信息] 拉取成功")
        return True
    else:
        print(f"[错误] 拉取失败: {err}")
        if "conflict" in err.lower():
            print("[提示] 存在冲突，请手动解决后再次运行脚本。")
            print("       解决后执行: git rebase --continue 或 git merge --continue")
        return False

def push_to_remote(repo_path, branch):
    """推送本地提交到远程"""
    print(f"[信息] 推送到 origin/{branch} ...")
    success, _, err = run_git_command(["git", "push", "origin", branch], cwd=repo_path)
    if success:
        print("[信息] 推送成功")
        return True
    else:
        print(f"[错误] 推送失败: {err}")
        # 常见错误：远程有更新
        if "rejected" in err.lower():
            print("[提示] 远程包含本地没有的提交，请先运行 pull 同步")
        return False

def action_push():
    """推送本地存档到 GitHub"""
    save_path = get_save_path()
    if not save_path.exists():
        print(f"[错误] 存档文件夹不存在: {save_path}")
        return False

    # 确保是 Git 仓库（如果尚未初始化，请用户提供远程 URL）
    if not is_git_repo(save_path):
        print("[信息] 存档文件夹还不是 Git 仓库，需要初始化")
        remote_url = input("请输入 GitHub 仓库地址 (SSH 或 HTTPS): ").strip()
        if not remote_url:
            print("[错误] 未提供远程仓库地址，无法继续")
            return False
        if not init_git_repo(save_path, remote_url):
            return False

    branch = get_current_branch(save_path)
    # 提交本地更改
    from datetime import datetime
    msg = COMMIT_MESSAGE.format(timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    if not commit_local_changes(save_path, msg):
        return False

    # 推送
    return push_to_remote(save_path, branch)

def action_pull():
    """从 GitHub 拉取存档到本地"""
    save_path = get_save_path()
    if not save_path.exists():
        print(f"[错误] 存档文件夹不存在: {save_path}")
        return False

    if not is_git_repo(save_path):
        print("[错误] 存档文件夹不是 Git 仓库，请先使用 push 功能初始化")
        return False

    branch = get_current_branch(save_path)

    # 可选：自动提交本地未推送的更改，避免被覆盖
    if AUTO_COMMIT_BEFORE_PULL:
        from datetime import datetime
        msg = COMMIT_MESSAGE.format(timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        commit_local_changes(save_path, msg)  # 忽略失败（无更改时也会成功）

    # 拉取更新
    return pull_from_remote(save_path, branch)

def action_sync():
    """先拉取再推送，实现双向同步"""
    if not action_pull():
        print("[错误] 拉取阶段失败，中止同步")
        return False
    if not action_push():
        print("[错误] 推送阶段失败，请手动检查")
        return False
    print("[信息] 双向同步完成")
    return True

def main():
    parser = argparse.ArgumentParser(description="游戏存档 GitHub 同步工具")
    parser.add_argument("action", choices=["push", "pull", "sync"],
                        help="push: 上传本地存档; pull: 下载远程存档; sync: 先下载再上传")
    args = parser.parse_args()

    # 允许通过环境变量覆盖存档文件夹名
    global SAVE_FOLDER
    env_folder = os.environ.get("GAME_SAVE_FOLDER")
    if env_folder:
        SAVE_FOLDER = env_folder
        print(f"[信息] 使用环境变量指定的存档文件夹: {SAVE_FOLDER}")

    if args.action == "push":
        success = action_push()
    elif args.action == "pull":
        success = action_pull()
    else:  # sync
        success = action_sync()

    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
