# Timestamped operator, system, safety, or processing event.
std_msgs/Header header
unique_identifier_msgs/UUID episode_id
unique_identifier_msgs/UUID event_id
string<=64 source_id

uint8 KIND_OPERATOR=0
uint8 KIND_SYSTEM=1
uint8 KIND_SAFETY=2
uint8 KIND_PROCESSING=3
uint8 kind

uint16 event_code
string<=256 summary
string<=1024 detail
