import ARKit
import PoseCore
import SceneKit
import SwiftUI

struct CameraPreview: UIViewRepresentable {
    let session: ARSession
    let packet: PosePacket?
    let fresh: Bool
    let estimate: RobotEstimate?

    func makeUIView(context: Context) -> ARSCNView {
        let view = ARSCNView(frame: .zero)
        view.session = session
        view.scene = SCNScene()
        view.backgroundColor = .black
        view.preferredFramesPerSecond = 30
        let marker = SCNNode()
        marker.name = "marker"
        marker.isHidden = true
        // Marker axes: +X right, +Y toward printed top/robot front, +Z out of paper.
        for (end, color, label) in [(SIMD3<Float>(0.045,0,0), UIColor.systemRed, "X"),
                                    (SIMD3<Float>(0,0.06,0), UIColor.systemGreen, "Y"),
                                    (SIMD3<Float>(0,0,0.04), UIColor.systemCyan, "Z")] {
            let material = SCNMaterial()
            material.diffuse.contents = color
            material.lightingModel = .constant
            material.readsFromDepthBuffer = false
            material.writesToDepthBuffer = false
            let length = simd_length(end), direction = simd_normalize(end)
            let shaft = SCNCylinder(radius: 0.0011, height: CGFloat(length - 0.007))
            shaft.materials = [material]
            let node = SCNNode(geometry: shaft)
            node.simdPosition = direction * (length - 0.007) / 2
            node.simdOrientation = simd_quatf(from: SIMD3<Float>(0,1,0), to: direction)
            node.renderingOrder = 100; marker.addChildNode(node)
            let head = SCNCone(topRadius: 0, bottomRadius: 0.0035, height: 0.009)
            head.materials = [material]
            let arrow = SCNNode(geometry: head)
            arrow.simdPosition = direction * (length - 0.0035)
            arrow.simdOrientation = node.simdOrientation
            arrow.renderingOrder = 101; marker.addChildNode(arrow)
            let text = SCNText(string: label, extrusionDepth: 0)
            text.font = .boldSystemFont(ofSize: 10); text.flatness = 0.2; text.materials = [material]
            let letter = SCNNode(geometry: text)
            letter.simdScale = SIMD3(repeating: 0.00065)
            letter.simdPosition = end + direction * 0.004
            letter.constraints = [SCNBillboardConstraint()]
            letter.renderingOrder = 102; marker.addChildNode(letter)
        }
        let centre = SCNSphere(radius: 0.002)
        centre.firstMaterial?.diffuse.contents = UIColor.white
        centre.firstMaterial?.lightingModel = .constant
        centre.firstMaterial?.readsFromDepthBuffer = false
        let origin = SCNNode(geometry: centre)
        origin.name = "origin"
        marker.addChildNode(origin)
        view.scene.rootNode.addChildNode(marker)
        return view
    }
    func updateUIView(_ view: ARSCNView, context: Context) {
        guard let marker = view.scene.rootNode.childNode(withName: "marker", recursively: false) else { return }
        marker.isHidden = !fresh || packet?.cameraTracking != "normal" || estimate == nil
        if let estimate {
            marker.simdTransform = PoseMath.fromRowMajor(estimate.worldFromTag)
            marker.opacity = estimate.isPredicted ? 0.5 : 1
            marker.childNode(withName: "origin", recursively: false)?.geometry?.firstMaterial?.diffuse.contents = estimate.isPredicted ? UIColor.systemOrange : UIColor.white
        }
    }
}
