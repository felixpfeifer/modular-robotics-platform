# Latest observable state of a command lease.
std_msgs/Header header
unique_identifier_msgs/UUID lease_id
string<=64 owner_id
string<=64 target_id

uint8 STATE_UNKNOWN=0
uint8 STATE_PENDING=1
uint8 STATE_ACTIVE=2
uint8 STATE_RELEASED=3
uint8 STATE_EXPIRED=4
uint8 STATE_REVOKED=5
uint8 STATE_DENIED=6
uint8 state

uint16 reason_code
string<=256 reason
