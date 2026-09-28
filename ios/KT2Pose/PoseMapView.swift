import PoseCore
import SwiftUI

struct PoseTrailPoint {
    let position: [Double]
    let predicted: Bool
    let startsSegment: Bool
}

/// Gravity-aligned top-down view: world X right, world -Z up, height in world Y.
struct PoseMapView: View {
    let camera: [Double]?
    let rawTag: [Double]?
    let estimate: RobotEstimate?
    let trail: [PoseTrailPoint]
    let waitingMessage: String
    private let green = Color(red: 0.62, green: 0.91, blue: 0.71)
    private var robotColor: Color { estimate?.isPredicted == true ? .orange : green }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("Pose map", systemImage: "location.north.line").font(.headline)
                Spacer()
                Text(estimate.map { $0.isPredicted ? "PREDICTED" : "FILTERED" } ?? "NO FIX")
                    .font(.caption2.bold()).foregroundStyle(estimate == nil ? .secondary : robotColor)
            }
            ZStack {
                Canvas { context, size in draw(context: &context, size: size) }
                if estimate == nil {
                    Text(waitingMessage).font(.subheadline).multilineTextAlignment(.center)
                        .padding(12).background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12))
                        .padding(28)
                }
            }.frame(height: 220).background(Color.black.opacity(0.22))
                .clipShape(RoundedRectangle(cornerRadius: 12))
                .accessibilityLabel("Top-down pose map. \(estimate?.isPredicted == true ? "Predicted robot position" : estimate == nil ? waitingMessage : "Filtered robot position"). World X points right and minus Z points up.")
            HStack(spacing: 14) {
                Label("Robot", systemImage: "circle.fill").foregroundStyle(robotColor)
                Label("Camera", systemImage: "location.north.fill").foregroundStyle(.blue)
                Spacer()
                Text("+x →  −z ↑").foregroundStyle(.secondary)
            }.font(.caption2)
            if let estimate {
                HStack {
                    Text(String(format: "Speed %.1f cm/s", sqrt(estimate.velocityWorldMps.reduce(0) { $0 + $1 * $1 }) * 100))
                    Spacer()
                    Text(String(format: "Seen %.2f s ago", estimate.observationAgeS))
                }.font(.caption).monospacedDigit().foregroundStyle(.secondary)
                let uncertainty = estimate.horizontalUncertainty
                HStack {
                    Text("Uncertainty · 2σ")
                    Spacer()
                    Text(String(format: "±%.1f × ±%.1f cm", uncertainty.majorStdM * 200, uncertainty.minorStdM * 200))
                }.font(.caption).monospacedDigit().foregroundStyle(robotColor)
                Text(estimate.isPredicted ? "Estimating through a gap · heading held from the last tag" : "Ring shows 2σ position spread · white dot is the raw tag")
                    .font(.caption2).foregroundStyle(.secondary)
            } else {
                Text("Predictions last up to 1 s. Start/reset camera to clear the map.")
                    .font(.caption2).foregroundStyle(.secondary)
            }
        }.padding(18).background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18))
    }

    private func draw(context: inout GraphicsContext, size: CGSize) {
        var points = trail.map(\.position)
        if let camera { points.append([camera[3], camera[7], camera[11]]) }
        if let estimate { points.append(estimate.positionWorldM) }
        let map = MapViewport(points: points, size: size)
        let grid = map.scale > 180 ? 0.1 : map.scale > 70 ? 0.25 : map.scale > 30 ? 0.5 : 1.0
        var lines = Path()
        let halfWidth = Double(size.width) / (2 * map.scale), halfHeight = Double(size.height) / (2 * map.scale)
        for x in stride(from: floor((map.x - halfWidth) / grid) * grid, through: map.x + halfWidth, by: grid) {
            let point = map.point(x, map.z)
            lines.move(to: CGPoint(x: point.x, y: 0)); lines.addLine(to: CGPoint(x: point.x, y: size.height))
        }
        for z in stride(from: floor((map.z - halfHeight) / grid) * grid, through: map.z + halfHeight, by: grid) {
            let point = map.point(map.x, z)
            lines.move(to: CGPoint(x: 0, y: point.y)); lines.addLine(to: CGPoint(x: size.width, y: point.y))
        }
        context.stroke(lines, with: .color(.white.opacity(0.09)), lineWidth: 1)
        for index in trail.indices.dropFirst() where !trail[index].startsSegment {
            var segment = Path()
            segment.move(to: map.point(trail[index - 1].position[0], trail[index - 1].position[2]))
            segment.addLine(to: map.point(trail[index].position[0], trail[index].position[2]))
            let predicted = trail[index].predicted || trail[index - 1].predicted
            context.stroke(segment, with: .color((predicted ? Color.orange : green).opacity(estimate == nil ? 0.3 : 0.65)),
                style: StrokeStyle(lineWidth: 2, dash: predicted ? [3, 3] : []))
        }
        if let camera {
            arrow(context: &context, point: map.point(camera[3], camera[11]),
                  dx: -camera[2], dz: -camera[10], color: .blue, radius: 5)
        }
        if let estimate {
            let point = map.point(estimate.positionWorldM[0], estimate.positionWorldM[2])
            let uncertainty = estimate.horizontalUncertainty
            let rx = 2 * uncertainty.majorStdM * map.scale, ry = 2 * uncertainty.minorStdM * map.scale
            let oval = Path(ellipseIn: CGRect(x: -rx, y: -ry, width: 2 * rx, height: 2 * ry))
            var ellipseContext = context
            ellipseContext.translateBy(x: point.x, y: point.y)
            ellipseContext.rotate(by: .radians(uncertainty.angleRadians))
            ellipseContext.fill(oval, with: .color(robotColor.opacity(0.18)))
            ellipseContext.stroke(oval, with: .color(robotColor.opacity(0.85)), style: StrokeStyle(lineWidth: 1.5, dash: estimate.isPredicted ? [4, 3] : []))
            arrow(context: &context, point: point, dx: estimate.worldFromTag[1], dz: estimate.worldFromTag[9], color: robotColor, radius: 3.5)
            if let rawTag {
                let raw = map.point(rawTag[3], rawTag[11])
                context.fill(Path(ellipseIn: CGRect(x: raw.x - 2.5, y: raw.y - 2.5, width: 5, height: 5)), with: .color(.white))
            }
        }
        let length = grid * map.scale
        var bar = Path()
        bar.move(to: CGPoint(x: 12, y: size.height - 14)); bar.addLine(to: CGPoint(x: 12 + length, y: size.height - 14))
        context.stroke(bar, with: .color(.white.opacity(0.8)), lineWidth: 2)
        context.draw(Text(String(format: "%.0f cm", grid * 100)).font(.system(size: 10)).foregroundColor(.secondary),
                     at: CGPoint(x: 12, y: size.height - 24), anchor: .leading)
    }

    private func arrow(context: inout GraphicsContext, point: CGPoint, dx: Double, dz: Double, color: Color, radius: Double) {
        context.fill(Path(ellipseIn: CGRect(x: point.x - radius, y: point.y - radius, width: 2 * radius, height: 2 * radius)), with: .color(color))
        let length = hypot(dx, dz)
        guard length > 0.05 else { return }
        let x = dx / length, z = dz / length
        var arrow = Path()
        arrow.move(to: point); arrow.addLine(to: CGPoint(x: point.x + x * 25, y: point.y + z * 25))
        arrow.addLine(to: CGPoint(x: point.x + x * 17 - z * 5, y: point.y + z * 17 + x * 5))
        arrow.move(to: CGPoint(x: point.x + x * 25, y: point.y + z * 25))
        arrow.addLine(to: CGPoint(x: point.x + x * 17 + z * 5, y: point.y + z * 17 - x * 5))
        context.stroke(arrow, with: .color(color), style: StrokeStyle(lineWidth: 2.5, lineCap: .round, lineJoin: .round))
    }
}

private struct MapViewport {
    let x: Double, z: Double, scale: Double
    let size: CGSize
    init(points: [[Double]], size: CGSize) {
        let xs = points.map { $0[0] }, zs = points.map { $0[2] }
        let minX = xs.min() ?? 0, maxX = xs.max() ?? 0, minZ = zs.min() ?? 0, maxZ = zs.max() ?? 0
        x = (minX + maxX) / 2; z = (minZ + maxZ) / 2
        scale = max(1, min((Double(size.width) - 64) / max(0.8, maxX - minX + 0.2),
                          (Double(size.height) - 64) / max(0.6, maxZ - minZ + 0.2)))
        self.size = size
    }
    func point(_ x: Double, _ z: Double) -> CGPoint {
        CGPoint(x: Double(size.width) / 2 + (x - self.x) * scale, y: Double(size.height) / 2 + (z - self.z) * scale)
    }
}
