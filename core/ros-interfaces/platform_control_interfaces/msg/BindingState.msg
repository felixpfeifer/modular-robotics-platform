# Observable eligibility and ownership state for one binding.
std_msgs/Header header
string<=64 binding_id
bool enabled
bool eligible
bool owns_command_lease
unique_identifier_msgs/UUID lease_id
uint16 reason_code
string<=256 reason
