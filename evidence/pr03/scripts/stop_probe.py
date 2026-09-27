#!/usr/bin/env python3
"""Измерить, сколько черепаха едет после Ctrl+C у patrol.

Подписывается на /turtle1/pose, ждёт первую позу, 1 с пишет позы в движении, затем шлёт SIGINT
группе процессов patrol (как Ctrl+C в терминале) и ещё 3 с пишет позы.
Печатает момент последнего изменения позы относительно SIGINT.

Запуск: python3 stop_probe.py <PGID процесса ros2 run patrol>
"""

import os
import signal
import sys
import time

import rclpy
from turtlesim.msg import Pose


def main():
    pgid = int(sys.argv[1])
    rclpy.init()
    node = rclpy.create_node('pr03_stop_probe')
    samples = []
    node.create_subscription(
        Pose, '/turtle1/pose',
        lambda m: samples.append((time.monotonic(), m.x, m.y, m.theta, m.linear_velocity)), 10)

    def spin_for(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            rclpy.spin_once(node, timeout_sec=0.02)

    deadline = time.monotonic() + 10.0
    while not samples and time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.1)
    if not samples:
        print('ERROR: /turtle1/pose не приходит за 10 с')
        return 1
    spin_for(1.0)
    before = samples[-1]
    t_sigint = time.monotonic()
    os.killpg(pgid, signal.SIGINT)
    spin_for(3.0)

    after = [s for s in samples if s[0] >= t_sigint]
    last_moving = None
    for prev, cur in zip(after, after[1:]):
        if (cur[1], cur[2], cur[3]) != (prev[1], prev[2], prev[3]):
            last_moving = cur
    final = samples[-1]
    print(f'SIGINT отправлен группе {pgid}')
    print(f'до SIGINT: x={before[1]:.4f} y={before[2]:.4f} theta={before[3]:.4f} '
          f'linear_velocity={before[4]:.2f}')
    if last_moving is None:
        print('после SIGINT поза не менялась')
    else:
        print(f'последнее изменение позы через {last_moving[0] - t_sigint:.3f} с после SIGINT')
    print(f'через {final[0] - t_sigint:.1f} с: x={final[1]:.4f} y={final[2]:.4f} '
          f'theta={final[3]:.4f} linear_velocity={final[4]:.2f}')
    print(f'поз получено после SIGINT: {len(after)}')
    node.destroy_node()
    rclpy.try_shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
