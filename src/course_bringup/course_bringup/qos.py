"""Чистые функции: профили QoS сенсорного потока sensor_pose и его подписчика."""

from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

DEPTH = 10

RELIABILITY = {
    'reliable': ReliabilityPolicy.RELIABLE,
    'best_effort': ReliabilityPolicy.BEST_EFFORT,
}


def sensor_qos():
    """Профиль издателя sensor_pose: best effort, keep last 10, volatile."""
    return QoSProfile(
        history=HistoryPolicy.KEEP_LAST, depth=DEPTH,
        reliability=ReliabilityPolicy.BEST_EFFORT, durability=DurabilityPolicy.VOLATILE)


def listener_qos(reliability):
    """Профиль подписчика: reliability из параметра, остальное как у сенсора."""
    if reliability not in RELIABILITY:
        raise ValueError(f'reliability must be one of {sorted(RELIABILITY)}, got {reliability!r}')
    return QoSProfile(
        history=HistoryPolicy.KEEP_LAST, depth=DEPTH,
        reliability=RELIABILITY[reliability], durability=DurabilityPolicy.VOLATILE)
