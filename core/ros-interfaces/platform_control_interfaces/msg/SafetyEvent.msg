# Timestamped safety transition, limit, or rejection.
std_msgs/Header header
unique_identifier_msgs/UUID event_id
# All-zero UUID when no command is correlated.
unique_identifier_msgs/UUID command_id
string<=64 source_id
string<=64 target_id

uint8 SEVERITY_INFO=0
uint8 SEVERITY_WARNING=1
uint8 SEVERITY_ERROR=2
uint8 SEVERITY_FATAL=3
uint8 severity

uint16 event_code
string<=256 summary
string<=1024 detail
