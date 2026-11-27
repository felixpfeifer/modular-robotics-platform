# Named, time-bounded joint command. Arrays align exactly by joint_names.
unique_identifier_msgs/UUID command_id
unique_identifier_msgs/UUID lease_id
string<=64 source_id
string<=64 target_id
builtin_interfaces/Time issued_at
builtin_interfaces/Time valid_until
string<=64[<=32] joint_names
# Position in radians for revolute joints or metres for prismatic joints.
float64[<=32] positions
# Optional rad/s or m/s values. Empty means unspecified, not zero.
float64[<=32] velocities
# Optional rad/s^2 or m/s^2 values. Empty means unspecified.
float64[<=32] accelerations
