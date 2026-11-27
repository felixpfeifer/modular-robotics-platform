# Immutable calibration reference. Calibration content is stored externally.
string<=64 calibration_id
string<=64 calibration_type
string<=32 version
string<=128 content_hash
# REP-103 frame identifiers. Empty only when the calibration has no frame pair.
string<=128 parent_frame
string<=128 child_frame
