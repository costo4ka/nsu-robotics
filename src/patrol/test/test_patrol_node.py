"""Функциональные тесты ноды patrol в одном процессе, без turtlesim."""

import os
import time

from geometry_msgs.msg import Twist
from patrol.patrol import Patrol
import pytest
import rclpy
from rclpy.context import Context
from rclpy.exceptions import InvalidParameterValueException
from rclpy.executors import SingleThreadedExecutor
from rclpy.parameter import Parameter
from turtlesim.msg import Pose

# Свои имена на каждый процесс: тест не мешает работающему turtlesim
# и параллельной копии теста в том же домене.
TEST_NS = f'/patrol_test_{os.getpid()}'
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


@pytest.fixture
def system(context):
    """Patrol на тестовых топиках, probe с издателем позы и подписчиком команд."""
    # Своё имя ноды: ros2 param set /patrol к живой patrol в том же домене сюда не попадёт.
    patrol = Patrol(context=context, cli_args=[
        '--ros-args',
        '-r', f'__node:=patrol_test_{os.getpid()}',
        '-r', f'/turtle1/pose:={TEST_POSE_TOPIC}',
        '-r', f'cmd_vel:={TEST_CMD_TOPIC}',
    ])
    probe = rclpy.create_node(f'patrol_probe_{os.getpid()}', context=context)
    commands = []
    stamps = []

    def on_command(command):
        commands.append(command)
        stamps.append(time.monotonic())

    probe.create_subscription(Twist, TEST_CMD_TOPIC, on_command, 10)
    pose_pub = probe.create_publisher(Pose, TEST_POSE_TOPIC, 10)
    executor = SingleThreadedExecutor(context=context)
    executor.add_node(patrol)
    executor.add_node(probe)
    yield patrol, executor, commands, stamps, pose_pub
    executor.shutdown()
    probe.destroy_node()
    patrol.destroy_node()


def median_interval(executor, stamps, count=8):
    """Дождаться count новых команд и вернуть медианный интервал между ними."""
    start = len(stamps)
    assert spin_until(executor, lambda: len(stamps) >= start + count + 1)
    window = stamps[start:]
    intervals = sorted(later - earlier for earlier, later in zip(window, window[1:]))
    return intervals[len(intervals) // 2]


def set_parameter(node, name, value):
    (result,) = node.set_parameters([Parameter(name, value=value)])
    return result


def test_parameters_have_defaults_and_one_timer(context):
    node = Patrol(context=context)
    try:
        assert node.get_parameter('linear_speed').value == 0.5
        assert node.get_parameter('turn_rate').value == 0.3
        assert node.get_parameter('publish_hz').value == 10.0
        assert list(node.timers) == [node.timer]
        assert node.timer.timer_period_ns == 100_000_000
    finally:
        node.destroy_node()


def test_publish_hz_change_replaces_timer(context):
    node = Patrol(context=context)
    try:
        old_timer = node.timer
        assert set_parameter(node, 'publish_hz', 5.0).successful
        assert node.get_parameter('publish_hz').value == 5.0
        assert node.timer is not old_timer
        assert list(node.timers) == [node.timer]
        assert node.timer.timer_period_ns == 200_000_000
    finally:
        node.destroy_node()


@pytest.mark.parametrize('value', [0.0, -5.0, float('nan'), float('inf'), 31.0])
def test_invalid_publish_hz_is_rejected_and_timer_kept(context, value):
    node = Patrol(context=context)
    try:
        old_timer = node.timer
        result = set_parameter(node, 'publish_hz', value)
        assert not result.successful
        assert result.reason.startswith('publish_hz ')
        assert node.get_parameter('publish_hz').value == 10.0
        assert node.settings.publish_hz == 10.0
        assert node.timer is old_timer
        assert list(node.timers) == [old_timer]
        assert old_timer.timer_period_ns == 100_000_000
        assert not old_timer.is_canceled()
    finally:
        node.destroy_node()


def test_atomic_change_with_one_invalid_value_changes_nothing(context):
    node = Patrol(context=context)
    try:
        old_timer = node.timer
        result = node.set_parameters_atomically([
            Parameter('publish_hz', value=5.0), Parameter('linear_speed', value=2.0)])
        assert not result.successful
        assert node.get_parameter('publish_hz').value == 10.0
        assert node.get_parameter('linear_speed').value == 0.5
        assert node.timer is old_timer
    finally:
        node.destroy_node()


def test_invalid_startup_value_is_rejected(context):
    with pytest.raises(InvalidParameterValueException):
        Patrol(context=context, parameter_overrides=[Parameter('publish_hz', value=0.0)])


def test_valid_startup_value_sets_timer_period(context):
    node = Patrol(context=context, cli_args=['--ros-args', '-p', 'publish_hz:=5.0'])
    try:
        assert node.timer.timer_period_ns == 200_000_000
    finally:
        node.destroy_node()


def test_stream_rate_follows_publish_hz_and_survives_zero(system):
    patrol, executor, _, stamps, _ = system
    assert median_interval(executor, stamps) == pytest.approx(0.1, abs=0.03)

    assert set_parameter(patrol, 'publish_hz', 5.0).successful
    median_interval(executor, stamps, count=1)  # пропустить стык старого и нового таймера
    assert median_interval(executor, stamps) == pytest.approx(0.2, abs=0.03)

    result = set_parameter(patrol, 'publish_hz', 0.0)
    assert not result.successful
    assert patrol.get_parameter('publish_hz').value == 5.0
    assert list(patrol.timers) == [patrol.timer]
    assert median_interval(executor, stamps) == pytest.approx(0.2, abs=0.03)


def test_speed_parameters_change_command(system):
    patrol, executor, commands, _, pose_pub = system
    pose = Pose(x=5.5, y=5.5, theta=0.0)
    assert spin_until(
        executor, lambda: commands and not is_zero(commands[-1]),
        on_tick=lambda: pose_pub.publish(pose))

    results = patrol.set_parameters([
        Parameter('linear_speed', value=0.8), Parameter('turn_rate', value=-0.5)])
    assert all(result.successful for result in results)
    assert spin_until(
        executor, lambda: (commands[-1].linear.x, commands[-1].angular.z) == (0.8, -0.5))

    assert not set_parameter(patrol, 'linear_speed', 1.5).successful
    count = len(commands)
    assert spin_until(executor, lambda: len(commands) >= count + 3)
    assert (commands[-1].linear.x, commands[-1].angular.z) == (0.8, -0.5)
