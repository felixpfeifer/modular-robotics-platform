# Observable command rejection; it does not define rejection policy.
std_msgs/Header header
unique_identifier_msgs/UUID rejection_id
unique_identifier_msgs/UUID command_id
string<=64 source_id
string<=64 target_id
uint16 reason_code
string<=256 reason
