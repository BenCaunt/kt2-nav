"""Exercise the OpenCV algorithm and physical marker scale with a synthetic image.

This is a desktop algorithm check, not a substitute for running the iOS bridge.
"""
import pytest

cv = pytest.importorskip("cv2")
import numpy as np


def test_printed_dictionary_marker_pose_with_arkit_style_intrinsics():
    dictionary = cv.aruco.getPredefinedDictionary(cv.aruco.DICT_4X4_50)
    marker = cv.aruco.generateImageMarker(dictionary, 0, 300, borderBits=1)
    h = .025 / 2
    obj = np.array([[-h,h,0],[h,h,0],[h,-h,0],[-h,-h,0]], dtype=np.float64)
    K = np.array([[1600,0,960],[0,1600,720],[0,0,1]], dtype=np.float64)
    actual_r = np.array([np.pi-.4,0,0], dtype=np.float64)
    actual_t = np.array([.03,.015,.35], dtype=np.float64)
    image_points = cv.projectPoints(obj,actual_r,actual_t,K,None)[0].reshape(4,2)
    H = cv.getPerspectiveTransform(np.float32([[0,0],[299,0],[299,299],[0,299]]), image_points.astype(np.float32))
    image = cv.warpPerspective(marker,H,(1920,1440),borderValue=255)
    params = cv.aruco.DetectorParameters()
    params.cornerRefinementMethod = cv.aruco.CORNER_REFINE_SUBPIX
    corners, ids, _ = cv.aruco.ArucoDetector(dictionary,params).detectMarkers(image)
    assert ids.flatten().tolist() == [0]
    _, rotations, translations, _ = cv.solvePnPGeneric(obj,corners[0],K,None,flags=cv.SOLVEPNP_IPPE_SQUARE)
    candidates=[]
    for r,t in zip(rotations,translations):
        projected=cv.projectPoints(obj,r,t,K,None)[0].reshape(4,2)
        error=np.sqrt(np.mean(np.sum((projected-corners[0][0])**2,axis=1)))
        candidates.append((error,r,t))
    error,r,t=min(candidates,key=lambda item:item[0])
    assert error < 2.5
    assert np.linalg.norm(t.ravel()-actual_t) < .005
    R=cv.Rodrigues(r)[0]
    actual_R=cv.Rodrigues(actual_r)[0]
    angle=np.arccos(np.clip((np.trace(R.T@actual_R)-1)/2,-1,1))
    assert np.rad2deg(angle) < 5
