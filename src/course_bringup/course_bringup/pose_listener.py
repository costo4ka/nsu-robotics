"""Нода pose_listener: подписчик sensor_pose с QoS из параметра reliability."""

import signal

from course_bringup.qos import listener_qos
from rcl_interfaces.msg import ParameterDescriptor
import rclpy
from rclpy.event_handler import SubscriptionEventCallbacks
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import qos_policy_name_from_kind
from turtlesim.msg import Pose

REPORT_PERIOD_SEC = 2.0


class PoseListener(Node):
    """Считает полученные сообщения и сообщает о несовместимом QoS издателя."""

    def __init__(self, **kwargs):
        super().__init__('pose_listener', **kwargs)
        self.declare_parameter('reliability', 'best_effort', ParameterDescriptor(
            description='QoS reliability of the sensor_pose subscription: reliable or best_effort',
            read_only=True))
        self.reliability = self.get_parameter('reliability').value
        self.received = 0
        self.incompatible_events = 0
        self.pose_sub = self.create_subscription(
            Pose, 'sensor_pose', self.on_pose, listener_qos(self.reliability),
            event_callbacks=SubscriptionEventCallbacks(incompatible_qos=self.on_incompatible_qos))
        self.report_timer = self.create_timer(REPORT_PERIOD_SEC, self.report)
        self.get_logger().info(
            f'subscribed to {self.pose_sub.topic_name} with reliability={self.reliability}')

    def on_pose(self, message):
        self.received += 1
        if self.received == 1:
            self.get_logger().info(f'first message: x={message.x:.3f} y={message.y:.3f}')

    def on_incompatible_qos(self, event):
        self.incompatible_events = event.total_count
        self.get_logger().warning(
            f'incompatible QoS with a publisher of {self.pose_sub.topic_name}: '
            f'last policy {qos_policy_name_from_kind(event.last_policy_kind)}, '
            f'total {event.total_count}')

    def report(self):
        self.get_logger().info(
            f'reliability={self.reliability}: received {self.received} messages')


def main(args=None):
    rclpy.init(args=args)
    node = PoseListener()
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
