"""Чистые функции: выбор команды patrol по последней позе."""

import math

from geometry_msgs.msg import Twist

PATROL_LINEAR_X = 0.5
PATROL_ANGULAR_Z = 0.3

MAX_LINEAR_X = 1.0
MAX_ANGULAR_Z = 1.0


def choose_command(pose):
    """Вернуть нулевой Twist, пока позы нет, иначе команду патрулирования."""
    if pose is None:
        return Twist()
    return limit_command(PATROL_LINEAR_X, PATROL_ANGULAR_Z)


def limit_command(linear_x, angular_z,
                  max_linear_x=MAX_LINEAR_X, max_angular_z=MAX_ANGULAR_Z):
    """Собрать Twist с ограниченными скоростями; остальные поля нулевые."""
    command = Twist()
    command.linear.x = _clamp(linear_x, max_linear_x)
    command.angular.z = _clamp(angular_z, max_angular_z)
    return command


def _clamp(value, limit):
    value = float(value)
    limit = float(limit)
    if not math.isfinite(value):
        return 0.0
    return max(-limit, min(limit, value))
