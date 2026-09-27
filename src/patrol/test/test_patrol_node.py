"""Функциональные тесты ноды patrol в одном процессе, без turtlesim."""

import os
import time

from geometry_msgs.msg import Twist
from patrol.patrol import Patrol
import pytest
import rclpy
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor
from turtlesim.msg import Pose

# Свои имена на каждый процесс: тест не мешает работающему turtlesim
# и параллельной копии теста в том же домене.
TEST_NS = f'/pr03_test_{os.getpid()}'
TEST_POSE_TOPIC = f'{TEST_NS}/pose'
TEST_CMD_TOPIC = f'{TEST_NS}/cmd_vel'


@pytest.fixture
def context():
    ctx = Context()
    rclpy.init(context=ctx)
    yield ctx
    rclpy.try_shutdown(context=ctx)


def spin_until(executor, condition, timeout_sec=5.0, on_tick=None):
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if on_tick is not None:
            on_tick()
        executor.spin_once(timeout_sec=0.05)
        if condition():
            return True
    return False


def is_zero(command):
    return command == Twist()


def test_graph_names_and_timer_period(context):
    node = Patrol(context=context)
    try:
        assert node.get_fully_qualified_name() == '/patrol'
        assert node.pose_sub.topic_name == '/turtle1/pose'
        # Относительное cmd_vel в корневом пространстве имён: это /cmd_vel, а не /turtle1/cmd_vel.
        assert node.cmd_pub.topic_name == '/cmd_vel'
        assert node.timer.timer_period_ns == 100_000_000
    finally:
        node.destroy_node()


def test_remap_resolves_cmd_vel_to_turtle_topic(context):
    node = Patrol(context=context, cli_args=['--ros-args', '-r', 'cmd_vel:=/turtle1/cmd_vel'])
    try:
        assert node.cmd_pub.topic_name == '/turtle1/cmd_vel'
    finally:
        node.destroy_node()


def test_zero_command_until_first_pose_then_patrol_command(context):
    patrol = Patrol(context=context, cli_args=[
        '--ros-args',
        '-r', f'/turtle1/pose:={TEST_POSE_TOPIC}',
        '-r', f'cmd_vel:={TEST_CMD_TOPIC}',
    ])
    probe = rclpy.create_node('pr03_probe', context=context)
    commands = []
    probe.create_subscription(Twist, TEST_CMD_TOPIC, commands.append, 10)
    pose_pub = probe.create_publisher(Pose, TEST_POSE_TOPIC, 10)
    executor = SingleThreadedExecutor(context=context)
    executor.add_node(patrol)
    executor.add_node(probe)
    try:
        assert spin_until(executor, lambda: len(commands) >= 3)
        assert patrol.latest_pose is None
        assert all(is_zero(command) for command in commands)

        pose = Pose(x=5.5, y=5.5, theta=0.0)
        assert spin_until(
            executor, lambda: not is_zero(commands[-1]),
            on_tick=lambda: pose_pub.publish(pose))
        assert patrol.latest_pose == pose
        assert commands[-1].linear.x == 0.5
        assert commands[-1].angular.z == 0.3
    finally:
        executor.shutdown()
        probe.destroy_node()
        patrol.destroy_node()
