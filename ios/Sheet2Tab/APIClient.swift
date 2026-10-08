import Foundation
import UIKit

struct TabNote: Codable, Identifiable {
    let pitch: String
    let midi: Int
    let duration: Double
    let measure: Int
    let offset: Double
    /// Beats (quarter notes) from the start of the piece. Optional: tabs saved before
    /// playback existed don't have it.
    let start: Double?
    /// Guitar only (1 = high e … 6 = low E); nil for piano.
    let string: Int?
    let fret: Int?
    /// Piano only: "right" or "left"; nil for guitar and tabs saved before piano mode.
    let hand: String?
    var id: String { "\(measure)-\(offset)-\(midi)-\(string ?? 0)-\(hand ?? "")" }
}

struct ConvertResponse: Codable {
    /// "guitar" or "piano". Optional: tabs saved before piano mode are guitar.
    let instrument: String?
    let tab_text: String
    let notes: [TabNote]
    /// Quarter notes per minute. Optional for tabs saved before playback existed.
    let tempo_bpm: Double?
    let warnings: [String]

    var isPiano: Bool { instrument == "piano" }
}

struct StageTiming: Decodable, Identifiable {
    let name: String
    let seconds: Double
    let done: Bool
    var id: String { name }
}

/// A background conversion on the server, polled via GET /jobs/{id}.
struct JobStatus: Decodable {
    let id: String
    let status: String  // queued | running | done | failed | cancelled
    let stage: String?
    let progress: Double
    let elapsed: Double
    let stages: [StageTiming]
    let result: ConvertResponse?
    let error: String?
}

enum APIError: LocalizedError {
    case badURL(String)
    case server(status: Int, message: String)
    case network(Error)
    case imageEncoding

    var errorDescription: String? {
        switch self {
        case .badURL(let s):
            return "Invalid backend URL: \"\(s)\". Set it in Settings, e.g. http://192.168.1.20:8000"
        case .server(let status, let message):
            return "Server error \(status): \(message)"
        case .network(let error):
            return "Could not reach the backend. Is the server running and is your phone on the same Wi-Fi?\n\n\(error.localizedDescription)"
        case .imageEncoding:
            return "Could not encode the photo as JPEG."
        }
    }
}

struct APIClient {
    let baseURL: String

    private static let session = URLSession(configuration: .default)

    private func url(_ path: String) throws -> URL {
        let trimmed = baseURL.trimmingCharacters(in: .whitespaces)
            .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard let url = URL(string: trimmed + path), url.scheme?.hasPrefix("http") == true,
              url.host != nil else {
            throw APIError.badURL(baseURL)
        }
        return url
    }

    func health() async throws {
        var request = URLRequest(url: try url("/health"))
        request.timeoutInterval = 5
        _ = try await send(request)
    }

    /// Uploads the pages (in order) and starts one conversion; poll `job(id:)` for progress.
    func startJob(images: [UIImage], instrument: String) async throws -> JobStatus {
        let boundary = "Boundary-\(UUID().uuidString)"
        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"instrument\"\r\n\r\n\(instrument)\r\n".data(using: .utf8)!)
        for (index, image) in images.enumerated() {
            guard let jpeg = image.downscaled(maxSide: 3000).jpegData(compressionQuality: 0.85) else {
                throw APIError.imageEncoding
            }
            body.append("--\(boundary)\r\n".data(using: .utf8)!)
            body.append("Content-Disposition: form-data; name=\"file\"; filename=\"page\(index + 1).jpg\"\r\n".data(using: .utf8)!)
            body.append("Content-Type: image/jpeg\r\n\r\n".data(using: .utf8)!)
            body.append(jpeg)
            body.append("\r\n".data(using: .utf8)!)
        }
        body.append("--\(boundary)--\r\n".data(using: .utf8)!)

        var request = URLRequest(url: try url("/jobs"))
        request.httpMethod = "POST"
        request.timeoutInterval = 120
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.httpBody = body

        let data = try await send(request)
        return try JSONDecoder().decode(JobStatus.self, from: data)
    }

    func job(id: String) async throws -> JobStatus {
        var request = URLRequest(url: try url("/jobs/\(id)"))
        request.timeoutInterval = 10
        let data = try await send(request)
        return try JSONDecoder().decode(JobStatus.self, from: data)
    }

    /// Stops a conversion on the server, so it doesn't keep running for minutes.
    func cancelJob(id: String) async throws {
        var request = URLRequest(url: try url("/jobs/\(id)"))
        request.httpMethod = "DELETE"
        request.timeoutInterval = 10
        _ = try await send(request)
    }

    private func send(_ request: URLRequest) async throws -> Data {
        let data: Data, response: URLResponse
        do {
            (data, response) = try await Self.session.data(for: request)
        } catch {
            throw APIError.network(error)
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            // FastAPI errors look like {"detail": "..."}
            let detail = (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["detail"]
            throw APIError.server(status: status, message: detail.map { "\($0)" }
                                  ?? String(decoding: data, as: UTF8.self))
        }
        return data
    }
}

extension UIImage {
    func downscaled(maxSide: CGFloat) -> UIImage {
        let longest = max(size.width, size.height)
        guard longest > maxSide else { return self }
        let scale = maxSide / longest
        let newSize = CGSize(width: size.width * scale, height: size.height * scale)
        let format = UIGraphicsImageRendererFormat.default()
        format.scale = 1
        // Drawing also bakes in the photo's orientation.
        return UIGraphicsImageRenderer(size: newSize, format: format).image { _ in
            draw(in: CGRect(origin: .zero, size: newSize))
        }
    }
}
