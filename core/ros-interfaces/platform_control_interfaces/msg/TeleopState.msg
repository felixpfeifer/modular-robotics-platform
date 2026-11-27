# Vendor-neutral raw teleoperator observation.
# header.stamp is acquisition time; header.frame_id is the REP-103 pose frame.
std_msgs/Header header
unique_identifier_msgs/UUID sample_id
string<=64 source_id
geometry_msgs/Pose pose
# Linear values are m/s and angular values are rad/s in header.frame_id.
geometry_msgs/Twist velocity
# Normalized [0.0, 1.0]. Values outside this range are invalid.
float32 gripper_position
# Source-defined button bit mask documented by the producer contract.
uint32 buttons
bool clutch_engaged
bool tracking_valid
bool pose_valid
bool velocity_valid
