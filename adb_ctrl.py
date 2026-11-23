#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""adb_ctrl.py — MuMu Player 12 稳定 ADB 连接、触控（sendevent）与截屏工具"""

import base64
import subprocess
import sys
import time

ADB = r"D:\software\MuMu Player 12\nx_main\adb.exe"
SERIAL = "127.0.0.1:7555"


def ensure_connect() -> None:
    """确保 ADB 已连接至 127.0.0.1:7555。"""
    subprocess.run([ADB, "connect", SERIAL], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_adb(*args: str, binary: bool = False) -> bytes | str:
    """执行 adb 命令并返回输出。"""
    cmd = [ADB, "-s", SERIAL, *args]
    res = subprocess.run(cmd, check=True, capture_output=True)
    return res.stdout if binary else res.stdout.decode("utf-8", errors="replace")


def su_sh(script: str) -> str:
    """通过 Base64 编码执行 root shell 脚本，避免引号与换行转义问题。"""
    b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
    return run_adb("shell", f"su -c 'echo {b64} | base64 -d | sh'")


def tap_raw(rx: int, ry: int, hold_sec: float = 0.1) -> None:
    """向 /dev/input/event4 发送多点触控点击事件（原始硬件坐标 rx: 0..1080, ry: 0..1920）。"""
    ev = "/dev/input/event4"
    press_cmd = "\n".join([
        f"sendevent {ev} 3 47 0",
        f"sendevent {ev} 3 57 130",
        f"sendevent {ev} 3 53 {rx}",
        f"sendevent {ev} 3 54 {ry}",
        f"sendevent {ev} 1 330 1",
        f"sendevent {ev} 1 325 1",
        f"sendevent {ev} 0 0 0",
        f"sleep {hold_sec:.3f}",
        f"sendevent {ev} 3 57 -1",
        f"sendevent {ev} 1 330 0",
        f"sendevent {ev} 1 325 0",
        f"sendevent {ev} 0 0 0",
    ])
    su_sh(press_cmd)


def tap_logic(lx: int, ly: int) -> None:
    """根据横屏 SurfaceOrientation: 1 将逻辑坐标 (1920x1080) 映射至硬件坐标并点击。"""
    rx = 1080 - ly
    ry = lx
    print(f"tap logic=({lx}, {ly}) -> raw=({rx}, {ry})")
    tap_raw(rx, ry)


def screencap(out_path: str) -> None:
    """截取当前模拟器屏幕并保存至本地路径。"""
    raw = run_adb("exec-out", "screencap", "-p", binary=True)
    with open(out_path, "wb") as f:
        f.write(raw)
    print(f"saved screencap -> {out_path} ({len(raw)} bytes)")


def main() -> None:
    ensure_connect()
    args = sys.argv[1:]
    if not args:
        print("Usage: adb_ctrl.py shot <path> | tap <lx> <ly> [wait_s] [shot_path] | raw <rx> <ry> [wait_s] [shot_path]")
        sys.exit(1)

    i = 0
    while i < len(args):
        cmd = args[i]
        if cmd == "shot":
            screencap(args[i + 1])
            i += 2
        elif cmd == "tap":
            lx, ly = int(args[i + 1]), int(args[i + 2])
            tap_logic(lx, ly)
            i += 3
        elif cmd == "raw":
            rx, ry = int(args[i + 1]), int(args[i + 2])
            print(f"tap raw=({rx}, {ry})")
            tap_raw(rx, ry)
            i += 3
        elif cmd == "sleep":
            time.sleep(float(args[i + 1]))
            i += 2
        else:
            raise ValueError(f"Unknown cmd: {cmd}")


if __name__ == "__main__":
    main()
