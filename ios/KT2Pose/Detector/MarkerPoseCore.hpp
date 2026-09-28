#pragma once
#include <opencv2/core.hpp>
#include <opencv2/calib3d.hpp>
#include <opencv2/objdetect/aruco_detector.hpp>
#include <algorithm>
#include <cmath>
#include <limits>
#include <string>
#include <vector>

namespace kt2 {
struct Observation {
    std::string status = "not_detected";
    cv::Matx44d cameraFromTag = cv::Matx44d::eye();
    std::vector<cv::Point2f> corners;
    double error = 0, alternateError = -1, minimumEdge = 0;
    bool ambiguous = false;
};

class MarkerDetector {
    cv::aruco::ArucoDetector detector;
public:
    MarkerDetector() : detector(cv::aruco::getPredefinedDictionary(cv::aruco::DICT_4X4_50)) {
        auto parameters = detector.getDetectorParameters();
        parameters.cornerRefinementMethod = cv::aruco::CORNER_REFINE_SUBPIX;
        detector.setDetectorParameters(parameters);
    }

    Observation detect(const cv::Mat &gray, const cv::Matx33d &K) {
        Observation output;
        std::vector<int> ids;
        std::vector<std::vector<cv::Point2f>> corners;
        detector.detectMarkers(gray, corners, ids);
        int selected = -1;
        for (size_t i = 0; i < ids.size(); ++i) {
            if (ids[i] != 0) continue;
            if (selected >= 0) { output.status = "duplicate"; return output; }
            selected = static_cast<int>(i);
        }
        if (selected < 0) return output;
        output.corners = corners[selected];
        output.minimumEdge = std::numeric_limits<double>::infinity();
        for (int i = 0; i < 4; ++i)
            output.minimumEdge = std::min(output.minimumEdge, cv::norm(output.corners[i] - output.corners[(i+1)%4]));
        if (output.minimumEdge < 24) { output.status = "too_small"; return output; }
        // Standard sticker: BLACK square edge is 25 mm, not the 35 mm cut size.
        constexpr double h = 0.025 / 2;
        const std::vector<cv::Point3d> object = {{-h,h,0},{h,h,0},{h,-h,0},{-h,-h,0}};
        std::vector<cv::Mat> rotations, translations;
        cv::solvePnPGeneric(object, output.corners, K, cv::noArray(), rotations, translations,
                            false, cv::SOLVEPNP_IPPE_SQUARE);
        struct Candidate { cv::Matx33d R; cv::Vec3d t; double error; };
        std::vector<Candidate> candidates;
        for (size_t n = 0; n < rotations.size(); ++n) {
            cv::Mat R;
            cv::Rodrigues(rotations[n], R);
            cv::Matx33d rotation;
            cv::Vec3d translation;
            for (int r=0;r<3;++r) {
                translation[r] = translations[n].at<double>(r);
                for (int c=0;c<3;++c) rotation(r,c) = R.at<double>(r,c);
            }
            bool inFront = true;
            for (const auto &p : object) {
                const auto q = rotation * cv::Vec3d(p.x,p.y,p.z) + translation;
                if (!std::isfinite(q[2]) || q[2] <= 0) inFront = false;
            }
            if (!inFront) continue;
            std::vector<cv::Point2d> projected;
            cv::projectPoints(object, rotations[n], translations[n], K, cv::noArray(), projected);
            double sum = 0;
            for (int i=0;i<4;++i) {
                auto delta = projected[i] - cv::Point2d(output.corners[i]);
                sum += delta.dot(delta);
            }
            const double error = std::sqrt(sum/4);
            if (std::isfinite(error)) candidates.push_back({rotation, translation, error});
        }
        if (candidates.empty()) { output.status = "pose_failed"; return output; }
        std::sort(candidates.begin(), candidates.end(), [](const Candidate &a, const Candidate &b) { return a.error < b.error; });
        const auto &best = candidates[0];
        output.error = best.error;
        if (best.error > 2.5) { output.status = "pose_failed"; return output; }
        if (candidates.size() > 1) {
            output.alternateError = candidates[1].error;
            const auto delta = best.R.t() * candidates[1].R;
            const double cosine = std::clamp((cv::trace(delta)-1)/2, -1.0, 1.0);
            const double degrees = std::acos(cosine) * 180 / CV_PI;
            output.ambiguous = degrees > 10 && candidates[1].error - best.error < 0.35;
        }
        for (int r=0;r<3;++r) {
            for (int c=0;c<3;++c) output.cameraFromTag(r,c) = best.R(r,c);
            output.cameraFromTag(r,3) = best.t[r];
        }
        output.status = "detected";
        return output;
    }
};
}
