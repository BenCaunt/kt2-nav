// Include OpenCV before Foundation: Objective-C's YES/NO macros conflict with C++ headers.
#include "MarkerPoseCore.hpp"
#import "KTMarkerDetector.h"

@implementation KTMarkerObservation
- (instancetype)init {
    if ((self = [super init])) {
        _status = @"not_detected";
        _cornersPx = @[];
        _cameraFromTagCV = matrix_identity_float4x4;
    }
    return self;
}
@end

@implementation KTMarkerDetector {
    kt2::MarkerDetector _detector;
}
- (KTMarkerObservation *)detectPixelBuffer:(CVPixelBufferRef)buffer intrinsics:(simd_float3x3)intrinsics {
    KTMarkerObservation *result = [[KTMarkerObservation alloc] init];
    if (!CVPixelBufferIsPlanar(buffer) || CVPixelBufferGetPlaneCount(buffer) < 1 ||
        CVPixelBufferLockBaseAddress(buffer, kCVPixelBufferLock_ReadOnly) != kCVReturnSuccess) {
        result.status = @"error";
        return result;
    }
    try {
        // Work on the unrotated, full-resolution luma plane. Intrinsics are from THIS ARFrame.
        cv::Mat gray(static_cast<int>(CVPixelBufferGetHeightOfPlane(buffer, 0)),
                     static_cast<int>(CVPixelBufferGetWidthOfPlane(buffer, 0)), CV_8UC1,
                     CVPixelBufferGetBaseAddressOfPlane(buffer, 0), CVPixelBufferGetBytesPerRowOfPlane(buffer, 0));
        cv::Matx33d K;
        for (int r=0;r<3;++r) for (int c=0;c<3;++c) K(r,c) = intrinsics.columns[c][r];
        const auto observed = _detector.detect(gray, K);
        result.status = [NSString stringWithUTF8String:observed.status.c_str()];
        simd_float4x4 transform = matrix_identity_float4x4;
        for (int r=0;r<4;++r) for (int c=0;c<4;++c) transform.columns[c][r] = observed.cameraFromTag(r,c);
        result.cameraFromTagCV = transform;
        NSMutableArray<NSNumber *> *corners = [NSMutableArray array];
        for (const auto &p : observed.corners) { [corners addObject:@(p.x)]; [corners addObject:@(p.y)]; }
        result.cornersPx = corners;
        result.reprojectionErrorPx = observed.error;
        result.alternateErrorPx = observed.alternateError < 0 ? nil : @(observed.alternateError);
        result.minimumEdgePx = observed.minimumEdge;
        result.poseAmbiguous = observed.ambiguous;
    } catch (const std::exception &) {
        result.status = @"error";
    }
    CVPixelBufferUnlockBaseAddress(buffer, kCVPixelBufferLock_ReadOnly);
    return result;
}
@end
