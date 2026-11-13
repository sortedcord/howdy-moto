"""Standalone IR/NPU feasibility test. No files, enrollment, or authentication."""
import argparse
import configparser
from pathlib import Path
import time
import json
import cv2
import numpy as np
import openvino as ov

REFERENCE = np.array([
    (0.31556875, 0.461574107), (0.682622917, 0.461574107),
    (0.5002625, 0.640505357), (0.349471875, 0.824691964),
    (0.653436458, 0.824691964),
], dtype=np.float32) * 128


def tensor(image, compiled):
    _, _, h, w = compiled.input().shape
    return cv2.resize(image, (w, h)).transpose(2, 0, 1)[None].astype(np.float32)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--device', choices=['CPU', 'NPU'], default='NPU')
    args = parser.parse_args()
    cv2.setNumThreads(1)
    config = configparser.ConfigParser()
    config.read('/etc/howdy/config.ini')
    camera = cv2.VideoCapture(config.get('video', 'device_path'), cv2.CAP_V4L2)
    try:
        if not camera.isOpened():
            raise RuntimeError('Cannot open configured IR camera')
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 360)
        camera.set(cv2.CAP_PROP_FPS, 30)
        core = ov.Core()
        base = Path(__file__).resolve().parents[1] / 'models'
        names = ['face-detection-adas-0001', 'landmarks-regression-retail-0009',
                 'face-reidentification-retail-0095']
        detector, landmarks, encoder = [core.compile_model(base / f'{n}.xml', args.device) for n in names]
        print('Execution devices:', [m.get_property('EXECUTION_DEVICES') for m in (detector, landmarks, encoder)], flush=True)
        print('Capturing IR for 12 seconds; images/embeddings stay in memory.', flush=True)
        stats = dict(frames=0, dark_frames=0, no_face=0, multiple_faces=0, embeddings=0)
        similarities, det_ms, embedding_ms = [], [], []
        reference = None
        start = time.perf_counter()
        cpu_start = time.process_time()
        while time.perf_counter() - start < 12:
            ok, frame = camera.read()
            if not ok:
                raise RuntimeError('Camera frame read failed')
            stats['frames'] += 1
            if frame.ndim == 2:
                frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if np.mean(gray < 32) * 100 > config.getfloat('video', 'dark_threshold'):
                stats['dark_frames'] += 1
                continue
            tick = time.perf_counter()
            detections = detector([tensor(frame, detector)])[detector.output()].reshape(-1, 7)
            det_ms.append((time.perf_counter() - tick) * 1000)
            faces = [d for d in detections if d[0] >= 0 and d[2] > 0.6]
            if len(faces) != 1:
                stats['multiple_faces' if len(faces) > 1 else 'no_face'] += 1
                continue
            h, w = frame.shape[:2]
            x1, y1, x2, y2 = (faces[0][3:7] * [w, h, w, h]).astype(int)
            x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            tick = time.perf_counter()
            points = landmarks([tensor(crop, landmarks)])[landmarks.output()].reshape(5, 2)
            points = points * [crop.shape[1], crop.shape[0]]
            matrix, _ = cv2.estimateAffinePartial2D(points.astype(np.float32), REFERENCE, method=cv2.LMEDS)
            if matrix is None:
                continue
            aligned = cv2.warpAffine(crop, matrix, (128, 128))
            embedding = encoder([tensor(aligned, encoder)])[encoder.output()].reshape(-1)
            norm = np.linalg.norm(embedding)
            if not np.isfinite(embedding).all() or norm < 1e-8:
                continue
            embedding = embedding / norm
            embedding_ms.append((time.perf_counter() - tick) * 1000)
            if reference is None:
                reference = embedding.copy()
            else:
                similarities.append(float(np.dot(reference, embedding)))
            stats['embeddings'] += 1
        stats['wall_seconds'] = time.perf_counter() - start
        stats['process_cpu_seconds'] = time.process_time() - cpu_start
        stats['mean_detection_ms'] = float(np.mean(det_ms)) if det_ms else None
        stats['mean_alignment_embedding_ms'] = float(np.mean(embedding_ms)) if embedding_ms else None
        stats['same_session_cosine_percentiles_5_50_95'] = np.percentile(similarities, [5, 50, 95]).tolist() if similarities else None
        print(json.dumps(stats, indent=2), flush=True)
        print('NOT an identity check, accuracy evaluation, or spoof-resistance test.')
    finally:
        camera.release()


if __name__ == '__main__':
    main()
