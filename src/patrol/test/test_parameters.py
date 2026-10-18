"""Тесты чистых функций проверки параметров patrol."""

from patrol.parameters import apply_changes, check_value, Settings
import pytest

DEFAULT = Settings()


def test_defaults():
    assert DEFAULT == Settings(linear_speed=0.5, turn_rate=0.3, publish_hz=10.0)
    assert DEFAULT.period_sec == pytest.approx(0.1)


def test_publish_hz_10_to_5():
    settings, reason = apply_changes(DEFAULT, {'publish_hz': 5.0})
    assert reason is None
    assert settings == Settings(linear_speed=0.5, turn_rate=0.3, publish_hz=5.0)
    assert settings.period_sec == pytest.approx(0.2)


@pytest.mark.parametrize('value', [0.0, -5.0, float('nan'), float('inf'), 0.5, 30.5])
def test_invalid_publish_hz_keeps_previous_settings(value):
    settings, reason = apply_changes(DEFAULT, {'publish_hz': value})
    assert reason is not None and reason.startswith('publish_hz ')
    assert settings is DEFAULT
    assert settings.publish_hz == 10.0


@pytest.mark.parametrize(('name', 'value'), [
    ('linear_speed', 0.0), ('linear_speed', 1.0),
    ('turn_rate', -1.0), ('turn_rate', 1.0),
    ('publish_hz', 1.0), ('publish_hz', 30.0), ('publish_hz', 5),
])
def test_boundaries_are_accepted(name, value):
    assert check_value(name, value) is None


@pytest.mark.parametrize(('name', 'value'), [
    ('linear_speed', -0.1), ('linear_speed', 1.5), ('linear_speed', float('nan')),
    ('turn_rate', -1.5), ('turn_rate', 2.0), ('turn_rate', float('-inf')),
    ('publish_hz', '10'), ('publish_hz', True), ('publish_hz', None),
])
def test_invalid_values_are_rejected(name, value):
    assert check_value(name, value) is not None


def test_one_invalid_value_rejects_the_whole_change():
    settings, reason = apply_changes(DEFAULT, {'linear_speed': 0.8, 'publish_hz': 0.0})
    assert reason is not None
    assert settings is DEFAULT


def test_speeds_change_and_unknown_parameters_are_ignored():
    settings, reason = apply_changes(
        DEFAULT, {'linear_speed': 0.8, 'turn_rate': -0.5, 'use_sim_time': False})
    assert reason is None
    assert settings == Settings(linear_speed=0.8, turn_rate=-0.5, publish_hz=10.0)
