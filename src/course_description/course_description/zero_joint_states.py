"""
Нода zero_joint_states: нулевые положения подвижных сочленений для robot_state_publisher.

Нужна только для показа колёс и кулаков в /tf и RViz: без /joint_states
robot_state_publisher публикует лишь фиксированные звенья.
"""

import signal

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from sensor_msgs.msg import JointState

MOVING_JOINTS = [
    'front_left_steering_joint', 'front_right_steering_joint',
    'front_left_wheel_joint', 'front_right_wheel_joint',
    'rear_left_wheel_joint', 'rear_right_wheel_joint',
]


class ZeroJointStates(Node):
    """Раз в 0.1 с публикует JointState с нулевыми положениями."""

    def __init__(self, **kwargs):
        super().__init__('zero_joint_states', **kwargs)
        self.joints = list(self.declare_parameter('joints', MOVING_JOINTS).value)
        self.publisher = self.create_publisher(JointState, 'joint_states', 10)
        self.timer = self.create_timer(0.1, self.publish)

    def publish(self):
        message = JointState()
        message.header.stamp = self.get_clock().now().to_msg()
        message.name = self.joints
        message.position = [0.0] * len(self.joints)
        self.publisher.publish(message)


def main(args=None):
    rclpy.init(args=args)
    node = ZeroJointStates()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        # Ctrl+C в терминале получают и launch, и нода, затем launch шлёт SIGINT ещё раз.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
