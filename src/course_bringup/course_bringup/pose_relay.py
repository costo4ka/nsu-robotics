"""Нода pose_relay: пересылает позу (в launch — /turtle1/pose) в sensor_pose с best effort."""

import signal

from course_bringup.qos import sensor_qos
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from turtlesim.msg import Pose


class PoseRelay(Node):
    """Тестовый «сенсор»: каждая поза черепахи уходит дальше потоком best effort."""

    def __init__(self, **kwargs):
        super().__init__('pose_relay', **kwargs)
        self.sensor_pub = self.create_publisher(Pose, 'sensor_pose', sensor_qos())
        # Оба имени относительные: launch переназначает pose на /turtle1/pose глобальной черепахи.
        self.pose_sub = self.create_subscription(Pose, 'pose', self.sensor_pub.publish, 10)


def main(args=None):
    rclpy.init(args=args)
    node = PoseRelay()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        # Ctrl+C в терминале получают и launch, и нода, затем launch шлёт SIGINT ещё раз;
        # повторный сигнал во время уборки не должен превращать выход в traceback.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
