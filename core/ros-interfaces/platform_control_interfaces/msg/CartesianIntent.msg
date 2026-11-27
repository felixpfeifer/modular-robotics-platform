# Time-bounded Cartesian command representation; consumers decide acceptance.
unique_identifier_msgs/UUID command_id
unique_identifier_msgs/UUID lease_id
string<=64 source_id
string<=64 target_id
builtin_interfaces/Time issued_at
# Must be non-zero and later than issued_at.
builtin_interfaces/Time valid_until
# Required REP-103 reference frame for target_pose and target_velocity.
string<=128 reference_frame

uint8 MODE_ABSOLUTE=0
uint8 MODE_DELTA=1
uint8 mode

geometry_msgs/Pose target_pose
# Linear values are m/s; angular values are rad/s.
geometry_msgs/Twist target_velocity
# Non-negative m/s and rad/s limits; zero means no motion, not "unlimited".
float64 max_linear_speed
float64 max_angular_speed
