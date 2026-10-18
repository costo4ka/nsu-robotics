"""Тесты чистых функций QoS сенсорного потока."""

from course_bringup.qos import listener_qos, sensor_qos
import pytest
from rclpy.qos import (
    DurabilityPolicy, HistoryPolicy, qos_check_compatible, QoSCompatibility, ReliabilityPolicy)


def test_sensor_is_best_effort_keep_last_10_volatile():
    qos = sensor_qos()
    assert qos.reliability == ReliabilityPolicy.BEST_EFFORT
    assert qos.history == HistoryPolicy.KEEP_LAST
    assert qos.depth == 10
    assert qos.durability == DurabilityPolicy.VOLATILE


@pytest.mark.parametrize(('name', 'policy'), [
    ('reliable', ReliabilityPolicy.RELIABLE),
    ('best_effort', ReliabilityPolicy.BEST_EFFORT),
])
def test_listener_reliability_from_parameter(name, policy):
    assert listener_qos(name).reliability == policy
    assert listener_qos(name).depth == 10


@pytest.mark.parametrize('name', ['RELIABLE', 'besteffort', '', None])
def test_unknown_reliability_is_rejected(name):
    with pytest.raises(ValueError):
        listener_qos(name)


def test_reliable_listener_is_incompatible_with_best_effort_sensor():
    compatibility, reason = qos_check_compatible(sensor_qos(), listener_qos('reliable'))
    assert compatibility == QoSCompatibility.ERROR
    assert 'reliab' in reason.lower()


def test_best_effort_listener_is_compatible_with_sensor():
    # WARNING, а не OK: liveliness system_default у обоих статически не проверить.
    compatibility, reason = qos_check_compatible(sensor_qos(), listener_qos('best_effort'))
    assert compatibility != QoSCompatibility.ERROR, reason
