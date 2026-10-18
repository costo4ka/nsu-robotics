"""Функциональные тесты pose_relay и pose_listener в одном процессе, без turtlesim."""

import os
import time

from course_bringup.pose_listener import PoseListener
from course_bringup.pose_relay import PoseRelay
import pytest
import rclpy
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor
from rclpy.parameter import Parameter
from rclpy.qos import ReliabilityPolicy
from turtlesim.msg import Pose

# Своё пространство имён и топик позы на каждый процесс: тест не мешает живой системе
# и параллельной копии теста в том же домене.
TEST_NS = f'/pr05_test_{os.getpid()}'
TEST_POSE_TOPIC = f'{TEST_NS}/turtle_pose'
NS_ARGS = ['--ros-args', '-r', f'__ns:={TEST_NS}']


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


def make_system(context, reliability):
    relay = PoseRelay(context=context, cli_args=NS_ARGS + ['-r', f'pose:={TEST_POSE_TOPIC}'])
    listener = PoseListener(
        context=context, cli_args=NS_ARGS,
        parameter_overrides=[Parameter('reliability', value=reliability)])
    probe = rclpy.create_node(f'pr05_probe_{os.getpid()}', context=context)
    pose_pub = probe.create_publisher(Pose, TEST_POSE_TOPIC, 10)
    executor = SingleThreadedExecutor(context=context)
    for node in (relay, listener, probe):
        executor.add_node(node)
    return relay, listener, probe, pose_pub, executor


def destroy(executor, *nodes):
    executor.shutdown()
    for node in nodes:
        node.destroy_node()


def test_relative_names_resolve_in_namespace(context):
    relay = PoseRelay(context=context, cli_args=NS_ARGS)
    listener = PoseListener(context=context, cli_args=NS_ARGS)
    try:
        assert relay.get_fully_qualified_name() == f'{TEST_NS}/pose_relay'
        assert relay.pose_sub.topic_name == f'{TEST_NS}/pose'
        assert relay.sensor_pub.topic_name == f'{TEST_NS}/sensor_pose'
        assert listener.pose_sub.topic_name == f'{TEST_NS}/sensor_pose'
    finally:
        relay.destroy_node()
        listener.destroy_node()


def test_relay_offers_best_effort(context):
    relay, listener, probe, _, executor = make_system(context, 'best_effort')
    try:
        topic = f'{TEST_NS}/sensor_pose'
        assert spin_until(executor, lambda: probe.get_publishers_info_by_topic(topic))
        (info,) = probe.get_publishers_info_by_topic(topic)
        assert info.qos_profile.reliability == ReliabilityPolicy.BEST_EFFORT
    finally:
        destroy(executor, relay, listener, probe)


def test_best_effort_listener_receives_relayed_poses(context):
    relay, listener, probe, pose_pub, executor = make_system(context, 'best_effort')
    try:
        assert spin_until(
            executor, lambda: listener.received >= 5,
            on_tick=lambda: pose_pub.publish(Pose(x=1.0, y=2.0)))
        assert listener.incompatible_events == 0
    finally:
        destroy(executor, relay, listener, probe)


def test_reliable_listener_gets_nothing_and_reports_incompatible_qos(context):
    relay, listener, probe, pose_pub, executor = make_system(context, 'reliable')
    try:
        assert spin_until(
            executor, lambda: listener.incompatible_events > 0,
            on_tick=lambda: pose_pub.publish(Pose(x=1.0, y=2.0)))
        # Топик тот же, издатель есть, но за секунду не приходит ни одного сообщения.
        assert probe.get_publishers_info_by_topic(f'{TEST_NS}/sensor_pose')
        assert not spin_until(
            executor, lambda: listener.received > 0, timeout_sec=1.0,
            on_tick=lambda: pose_pub.publish(Pose(x=1.0, y=2.0)))
    finally:
        destroy(executor, relay, listener, probe)


def test_invalid_reliability_parameter_stops_the_node(context):
    with pytest.raises(ValueError):
        PoseListener(
            context=context, cli_args=NS_ARGS,
            parameter_overrides=[Parameter('reliability', value='sometimes')])
