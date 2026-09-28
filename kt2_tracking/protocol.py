"""Version 1 wire contract. Transforms are row-major, metres, column vectors."""
import math


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def matrix(value):
    if not isinstance(value, list) or len(value) != 16 or not all(number(x) for x in value):
        raise ValueError("Transforms must contain 16 finite row-major numbers")
    if any(abs(value[12+i] - [0, 0, 0, 1][i]) > 1e-4 for i in range(4)):
        raise ValueError("Invalid homogeneous transform")
    for i in range(3):
        for j in range(3):
            dot = sum(value[k*4+i] * value[k*4+j] for k in range(3))
            if abs(dot - int(i == j)) > .01:
                raise ValueError("Rotation is not orthonormal")
    a,b,c,d,e,f,g,h,i = [value[r*4+c] for r in range(3) for c in range(3)]
    if abs(a*(e*i-f*h)-b*(d*i-f*g)+c*(d*h-e*g)-1) > .01:
        raise ValueError("Rotation must be right handed")
    return value


def multiply(a, b):
    return [sum(a[r*4+k]*b[k*4+c] for k in range(4)) for r in range(4) for c in range(4)]


def validate_estimate(p):
    estimate = p.get("robot_estimate")
    if estimate is None:
        return
    if not isinstance(estimate, dict) or estimate.get("mode") not in {"filtered", "predicted"} or p["camera_tracking"] != "normal":
        raise ValueError("Invalid robot estimate mode or ARKit state")
    age = estimate.get("observation_age_s")
    if not number(age) or not 0 <= age <= 1:
        raise ValueError("Robot estimate exceeds prediction horizon")
    if estimate["mode"] == "filtered" and (not isinstance(p.get("tag"), dict) or p["tag"].get("pose_ambiguous") is not False):
        raise ValueError("Filtered estimate needs an unambiguous tag observation")
    for name, count in (("position_world_m", 3), ("velocity_world_mps", 3), ("position_std_m", 3), ("position_covariance_m2", 9)):
        value = estimate.get(name)
        if not isinstance(value, list) or len(value) != count or not all(number(x) for x in value):
            raise ValueError("Invalid robot estimate " + name)
    std = estimate["position_std_m"]
    if any(not 0 <= x <= .15 for x in std):
        raise ValueError("Invalid robot position uncertainty")
    covariance = estimate["position_covariance_m2"]
    for i in range(3):
        if abs(covariance[4*i] - std[i]**2) > 1e-9 or covariance[4*i] < 0:
            raise ValueError("Covariance diagonal does not match uncertainty")
        for j in range(3):
            if abs(covariance[i*3+j] - covariance[j*3+i]) > 1e-9:
                raise ValueError("Covariance must be symmetric")
            if covariance[4*i] * covariance[4*j] - covariance[i*3+j]**2 < -1e-12:
                raise ValueError("Covariance must be positive semidefinite")
    a,b,c,d,e,f,g,h,i = covariance
    if a*(e*i-f*h)-b*(d*i-f*g)+c*(d*h-e*g) < -1e-15:
        raise ValueError("Covariance must be positive semidefinite")
    transform = matrix(estimate.get("world_from_tag"))
    if any(abs(transform[index*4+3] - estimate["position_world_m"][index]) > 1e-6 for index in range(3)):
        raise ValueError("Estimate transform does not match position")


def validate_packet(p):
    if not isinstance(p, dict) or type(p.get("schema_version")) is not int or p.get("schema_version") != 1:
        raise ValueError("Expected schema_version 1")
    session = p.get("session_id")
    if not isinstance(session, str) or not 1 <= len(session) <= 64:
        raise ValueError("Invalid session_id")
    seq = p.get("sequence")
    if type(seq) is not int or not 0 <= seq <= 2**53:
        raise ValueError("Invalid sequence")
    for key in ("frame_timestamp_s", "sent_unix_s"):
        if not number(p.get(key)) or p[key] < 0:
            raise ValueError(f"Invalid {key}")
    if p.get("camera_tracking") not in {"normal", "limited", "not_available"}:
        raise ValueError("Invalid camera_tracking")
    if not isinstance(p.get("camera_tracking_reason"), str) or len(p["camera_tracking_reason"]) > 200:
        raise ValueError("Invalid camera tracking reason")
    camera = matrix(p.get("world_from_camera"))
    resolution = p.get("image_resolution")
    if not isinstance(resolution, list) or len(resolution) != 2 or not all(type(x) is int and 1 <= x <= 16384 for x in resolution):
        raise ValueError("Invalid image_resolution")
    intrinsics = p.get("intrinsics")
    if not isinstance(intrinsics, dict) or not all(number(intrinsics.get(k)) for k in ("fx", "fy", "cx", "cy")):
        raise ValueError("Invalid intrinsics")
    if intrinsics["fx"] <= 0 or intrinsics["fy"] <= 0:
        raise ValueError("Invalid focal length")
    statuses = {"detected", "not_detected", "duplicate", "too_small", "pose_failed", "error"}
    if p.get("tag_status") not in statuses:
        raise ValueError("Invalid tag_status")
    validate_estimate(p)
    tag = p.get("tag")
    if p["tag_status"] != "detected":
        if tag is not None:
            raise ValueError("Undetected tags must be null")
        return p
    if not isinstance(tag, dict) or tag.get("dictionary") != "DICT_4X4_50" or type(tag.get("id")) is not int or tag.get("id") != 0:
        raise ValueError("Expected DICT_4X4_50 ID 0")
    if not number(tag.get("side_length_m")) or abs(tag["side_length_m"] - .025) > 1e-6:
        raise ValueError("Standard marker black edge must be 0.025 m")
    if type(tag.get("pose_ambiguous")) is not bool:
        raise ValueError("Missing ambiguity flag")
    for key in ("reprojection_error_px", "minimum_edge_px"):
        if not number(tag.get(key)) or tag[key] < 0:
            raise ValueError(f"Invalid {key}")
    if tag["minimum_edge_px"] < 24 or tag["reprojection_error_px"] > 2.5:
        raise ValueError("Tag fails observation quality threshold")
    alt = tag.get("alternate_error_px")
    if alt is not None and (not number(alt) or alt < 0):
        raise ValueError("Invalid alternate pose error")
    corners = tag.get("corners_px")
    if not isinstance(corners, list) or len(corners) != 8 or not all(number(x) for x in corners):
        raise ValueError("Invalid tag corners")
    if any(not 0 <= corners[i] < resolution[i % 2] for i in range(8)):
        raise ValueError("Tag corners are outside the image")
    cv = matrix(tag.get("cv_camera_from_tag"))
    if cv[11] <= 0:
        raise ValueError("Tag is behind the camera")
    world = matrix(tag.get("world_from_tag"))
    conversion = [1,0,0,0, 0,-1,0,0, 0,0,-1,0, 0,0,0,1]
    expected = multiply(multiply(camera, conversion), cv)
    if max(abs(a-b) for a,b in zip(expected, world)) > 1e-3:
        raise ValueError("Tag world pose does not match camera pose and axis conversion")
    return p
