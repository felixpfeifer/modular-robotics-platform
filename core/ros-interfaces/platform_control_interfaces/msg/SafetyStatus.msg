# Current observable safety state. This message does not encode safety policy.
std_msgs/Header header
string<=64 component_id

uint8 LEVEL_UNKNOWN=0
uint8 LEVEL_NORMAL=1
uint8 LEVEL_LIMITED=2
uint8 LEVEL_STOPPED=3
uint8 LEVEL_FAULT=4
uint8 level

bool motion_permitted
uint16 limiting_condition
string<=256 summary
# Device, zone, command, or policy reference identifiers.
string<=64[<=32] related_ids
