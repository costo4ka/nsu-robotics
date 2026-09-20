# PR01 ROS graph

## Normal state

ROS_DOMAIN_ID=16

Nodes:
/teleop_turtle
/turtlesim

Topics:
/parameter_events [rcl_interfaces/msg/ParameterEvent]
/rosout [rcl_interfaces/msg/Log]
/turtle1/cmd_vel [geometry_msgs/msg/Twist]
/turtle1/color_sensor [turtlesim/msg/Color]
/turtle1/pose [turtlesim/msg/Pose]

Pose type:
turtlesim/msg/Pose

Example pose:
x: 4.200419902801514
y: 6.366792678833008
theta: -1.4079999923706055
linear_velocity: 0.0
angular_velocity: 0.0

## Broken state

turtlesim remained in ROS_DOMAIN_ID=16.
teleop and observer were switched to ROS_DOMAIN_ID=17.

Visible nodes:
/teleop_turtle

/turtlesim was not visible.

Reading /turtle1/pose timed out after 5 seconds:
exit=124

## Fixed state

teleop and observer were returned to ROS_DOMAIN_ID=16.

Visible nodes:
/teleop_turtle
/turtlesim

Reading /turtle1/pose succeeded:
exit=0

Conclusion: nodes in different ROS_DOMAIN_ID values do not discover each other. Returning the processes to the same domain restores communication.
