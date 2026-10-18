"""Структура patrol.launch.py: аргументы, namespace, remap, запись через IfCondition."""

import importlib.util
from pathlib import Path

from launch import LaunchContext
from launch.actions import DeclareLaunchArgument, ExecuteProcess, GroupAction
from launch.conditions import IfCondition
from launch_ros.actions import Node, PushRosNamespace
import pytest

LAUNCH_FILE = Path(__file__).resolve().parents[1] / 'launch' / 'patrol.launch.py'


@pytest.fixture
def entities():
    spec = importlib.util.spec_from_file_location('patrol_launch', LAUNCH_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.generate_launch_description().entities


def context(**arguments):
    ctx = LaunchContext()
    ctx.launch_configurations.update(arguments)
    return ctx


def by_type(entities, kind):
    # Точный тип: launch_ros Node — подкласс ExecuteProcess.
    return [entity for entity in entities if type(entity) is kind]


def test_arguments_and_defaults(entities):
    arguments = {a.name: a.default_value for a in by_type(entities, DeclareLaunchArgument)}
    assert set(arguments) == {'namespace', 'record', 'bag_dir', 'subscriber_reliability'}
    ctx = context()
    defaults = {name: ''.join(s.perform(ctx) for s in value) for name, value in arguments.items()}
    assert defaults == {
        'namespace': 'robot_a', 'record': 'false', 'bag_dir': 'evidence/pr05/bag',
        'subscriber_reliability': 'best_effort'}


def test_turtlesim_is_global_and_nodes_are_namespaced(entities):
    (turtlesim,) = by_type(entities, Node)
    assert turtlesim.node_package == 'turtlesim'
    (group,) = by_type(entities, GroupAction)
    actions = group.get_sub_entities()
    (push,) = by_type(actions, PushRosNamespace)
    assert actions.index(push) < actions.index(by_type(actions, Node)[0])
    names = [action.node_executable for action in by_type(actions, Node)]
    assert names == ['patrol', 'pose_relay', 'pose_listener']


def remaps(node):
    # launch_ros отдаёт remap только после запуска действия, поэтому читаем исходные правила.
    ctx = context()
    return [(''.join(s.perform(ctx) for s in a), ''.join(s.perform(ctx) for s in b))
            for a, b in node._Node__remappings]


def test_nodes_are_remapped_to_the_global_turtle(entities):
    (group,) = by_type(entities, GroupAction)
    patrol, relay, listener = by_type(group.get_sub_entities(), Node)
    assert remaps(patrol) == [('cmd_vel', '/turtle1/cmd_vel')]
    assert remaps(relay) == [('pose', '/turtle1/pose')]
    assert remaps(listener) == []


@pytest.mark.parametrize(('record', 'expected'), [('true', True), ('false', False)])
def test_recorder_runs_only_with_record_true(entities, record, expected):
    (recorder,) = by_type(entities, ExecuteProcess)
    assert isinstance(recorder.condition, IfCondition)
    assert recorder.condition.evaluate(context(record=record)) is expected


@pytest.mark.parametrize('namespace', ['robot_a', '/robot_a'])
def test_recorder_writes_mcap_of_the_namespaced_sensor_topic(entities, namespace):
    (recorder,) = by_type(entities, ExecuteProcess)
    ctx = context(namespace=namespace, bag_dir='evidence/pr05/bag')
    command = [''.join(s.perform(ctx) for s in part) for part in recorder.cmd]
    assert command == [
        'ros2', 'bag', 'record', '-s', 'mcap', '-o', 'evidence/pr05/bag',
        '--topics', '/robot_a/sensor_pose']
