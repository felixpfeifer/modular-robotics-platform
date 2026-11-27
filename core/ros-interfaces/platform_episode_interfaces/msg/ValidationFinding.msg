# Machine-readable result of one validation rule.
unique_identifier_msgs/UUID finding_id
unique_identifier_msgs/UUID episode_id
string<=64 rule_id

uint8 SEVERITY_INFO=0
uint8 SEVERITY_WARNING=1
uint8 SEVERITY_ERROR=2
uint8 SEVERITY_FATAL=3
uint8 severity

uint8 DISPOSITION_OPEN=0
uint8 DISPOSITION_ACCEPTED=1
uint8 DISPOSITION_REJECTED=2
uint8 DISPOSITION_WAIVED=3
uint8 disposition

# Inclusive occurrence range in ROS time. Equal values denote a point finding.
builtin_interfaces/Time start_time
builtin_interfaces/Time end_time
string<=256 summary
# Immutable artifact-relative evidence reference, never inline bulk content.
string<=128 evidence_reference
