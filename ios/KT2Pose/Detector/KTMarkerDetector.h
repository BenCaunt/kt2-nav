#import <Foundation/Foundation.h>
#import <CoreVideo/CoreVideo.h>
#import <simd/simd.h>

NS_ASSUME_NONNULL_BEGIN
@interface KTMarkerObservation : NSObject
@property(nonatomic, copy) NSString *status;
@property(nonatomic) simd_float4x4 cameraFromTagCV;
@property(nonatomic, copy) NSArray<NSNumber *> *cornersPx;
@property(nonatomic) double reprojectionErrorPx;
@property(nonatomic, nullable) NSNumber *alternateErrorPx;
@property(nonatomic) double minimumEdgePx;
@property(nonatomic) BOOL poseAmbiguous;
@end

@interface KTMarkerDetector : NSObject
- (KTMarkerObservation *)detectPixelBuffer:(CVPixelBufferRef)pixelBuffer
                               intrinsics:(simd_float3x3)intrinsics NS_SWIFT_NAME(detect(_:intrinsics:));
@end
NS_ASSUME_NONNULL_END
