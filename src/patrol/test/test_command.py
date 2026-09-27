"""Тесты чистой функции выбора команды."""

from geometry_msgs.msg import Twist
from patrol.command import choose_command, limit_command
import pytest
from turtlesim.msg import Pose


def assert_command(command, linear_x=0.0, angular_z=0.0):
    assert isinstance(command, Twist)
    assert (command.linear.x, command.linear.y, command.linear.z) == (linear_x, 0.0, 0.0)
    assert (command.angular.x, command.angular.y, command.angular.z) == (0.0, 0.0, angular_z)


def test_missing_pose_gives_zero_command():
    assert_command(choose_command(None))


def test_regular_pose_gives_patrol_command():
    pose = Pose(x=5.544444561004639, y=5.544444561004639, theta=0.0)
    assert_command(choose_command(pose), linear_x=0.5, angular_z=0.3)


def test_command_does_not_depend_on_pose_values():
    moving = Pose(x=10.9, y=0.1, theta=-3.1, linear_velocity=0.5, angular_velocity=0.3)
    assert_command(choose_command(moving), linear_x=0.5, angular_z=0.3)


def test_choose_command_keeps_pose_and_returns_new_message():
    pose = Pose(x=1.0, y=2.0, theta=0.5)
    first = choose_command(pose)
    second = choose_command(pose)
    first.linear.x = 9.0
    assert second.linear.x == 0.5
    assert pose == Pose(x=1.0, y=2.0, theta=0.5)


@pytest.mark.parametrize(
    ('linear_x', 'angular_z', 'expected_linear_x', 'expected_angular_z'),
    [
        (0.5, 0.3, 0.5, 0.3),
        (5.0, 2.0, 1.0, 1.0),
        (-5.0, -2.0, -1.0, -1.0),
        (float('nan'), float('inf'), 0.0, 0.0),
        (1, 0, 1.0, 0.0),
    ],
)
def test_limit_command(linear_x, angular_z, expected_linear_x, expected_angular_z):
    assert_command(
        limit_command(linear_x, angular_z),
        linear_x=expected_linear_x, angular_z=expected_angular_z)


def test_limit_command_custom_limits():
    assert_command(
        limit_command(0.8, -0.9, max_linear_x=0.5, max_angular_z=0.2),
        linear_x=0.5, angular_z=-0.2)


def test_limit_command_integer_limits():
    assert_command(
        limit_command(5, -5, max_linear_x=1, max_angular_z=2),
        linear_x=1.0, angular_z=-2.0)
