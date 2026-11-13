"""Experimental, local-only NPU face backend. Never saves camera images.

Authentication is fail-closed: errors/nonmatches return failure to existing PAM.
This provides no liveness or calibrated false-accept guarantee.
"""
import argparse
import configparser
import json
import os
from pathlib import Path
import pwd
import signal
import stat
import sys
import tempfile
import time

import cv2
import numpy as np
import openvino as ov

MODEL_DIR = Path('/usr/local/share/howdy-npu/models')
STATE_DIR = Path('/var/lib/howdy-npu')
CONFIG = Path('/etc/howdy/config.ini')
NAMES = ('face-detection-adas-0001', 'landmarks-regression-retail-0009',
         'face-reidentification-retail-0095')
FORMAT = 'openvino-ir-aligned-256-v1'
THRESHOLD = 0.85  # Conservative starting point, NOT a calibrated security guarantee.
REFERENCE = np.array([
    (0.31556875, 0.461574107), (0.682622917, 0.461574107),
    (0.5002625, 0.640505357), (0.349471875, 0.824691964),
    (0.653436458, 0.824691964),
], dtype=np.float32) * 128


def trusted(path):
    """Sensitive inputs must be root-owned and not group/world-writable."""
    path = Path(path)
    for item in (path, *path.parents):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError(f'Untrusted path: {item}')
    return path


def read_json(path):
    return json.loads(trusted(path).read_text())


def save_json(path, value):
    trusted(path.parent)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.new-')
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(value, out)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def state_path(user, active=False):
    uid = pwd.getpwnam(user).pw_uid
    return STATE_DIR / ('users' if active else 'enrollment') / f'{uid}.json'


def new_state(user):
    return {'format': FORMAT, 'user': user, 'threshold': THRESHOLD,
            'profiles': [], 'validation': []}


def load_state(user, active=False):
    value = read_json(state_path(user, active))
    if value.get('format') != FORMAT or value.get('user') != user:
        raise ValueError('Wrong face template format or user')
    if value.get('threshold') != THRESHOLD:
        raise ValueError('Unexpected threshold; requires explicit code review')
    return value


def templates(state):
    rows, labels = [], []
    for profile in state['profiles']:
        for embedding in profile['embeddings']:
            rows.append(embedding)
            labels.append(profile['label'])
    data = np.asarray(rows, dtype=np.float32)
    if data.ndim != 2 or data.shape[1] != 256 or not np.isfinite(data).all():
        raise ValueError('Missing or invalid face templates')
    norms = np.linalg.norm(data, axis=1)
    if np.any(abs(norms - 1) > 0.01):
        raise ValueError('Templates must be normalized')
    return data, labels


def score(embedding, data):
    values = data @ embedding
    index = int(np.argmax(values))
    return float(values[index]), index


class MatchGate:
    """Require 3 consecutive usable matches spanning at least 0.25 seconds."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.count = 0
        self.first = None

    def update(self, matched, now):
        if not matched:
            self.reset()
            return False
        if self.first is None:
            self.first = now
        self.count += 1
        return self.count >= 3 and now - self.first >= 0.25


class Pipeline:
    def __init__(self):
        cv2.setNumThreads(1)
        config = configparser.ConfigParser()
        config.read(trusted(CONFIG))
        if config.get('video', 'recording_plugin', fallback='opencv') != 'opencv':
            raise ValueError('NPU backend currently requires OpenCV capture')
        if config.getint('video', 'rotate', fallback=0) != 0:
            raise ValueError('NPU backend currently requires landscape camera')
        self.dark_threshold = config.getfloat('video', 'dark_threshold')
        self.camera = cv2.VideoCapture(config.get('video', 'device_path'), cv2.CAP_V4L2)
        if not self.camera.isOpened():
            self.close()
            raise RuntimeError('Cannot open configured IR camera')
        try:
            for key, prop in [('frame_width', cv2.CAP_PROP_FRAME_WIDTH),
                              ('frame_height', cv2.CAP_PROP_FRAME_HEIGHT),
                              ('device_fps', cv2.CAP_PROP_FPS)]:
                value = config.getint('video', key, fallback=-1)
                if value > 0:
                    self.camera.set(prop, value)
            core = ov.Core()
            # Explicit NPU compilation: never AUTO/HETERO or CPU fallback.
            self.models = []
            for name in NAMES:
                path = trusted(MODEL_DIR / f'{name}.xml')
                trusted(path.with_suffix('.bin'))
                model = core.compile_model(path, 'NPU')
                devices = model.get_property('EXECUTION_DEVICES')
                devices = [devices] if isinstance(devices, str) else devices
                if not devices or any(not d.startswith('NPU') for d in devices):
                    raise RuntimeError('Unexpected non-NPU execution device')
                self.models.append(model)
        except BaseException:
            self.close()
            raise

    def close(self):
        self.camera.release()

    @staticmethod
    def infer(image, model):
        _, _, h, w = model.input().shape
        data = cv2.resize(image, (w, h)).transpose(2, 0, 1)[None].astype(np.float32)
        return model([data])[model.output()]

    def read(self):
        ok, frame = self.camera.read()
        if not ok:
            raise RuntimeError('IR camera read failed')
        if frame.ndim == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if np.mean(gray < 32) * 100 > self.dark_threshold:
            return None, 'dark'
        detector, landmarks, encoder = self.models
        detections = self.infer(frame, detector).reshape(-1, 7)
        faces = [d for d in detections if d[0] >= 0 and d[2] >= 0.8]
        if len(faces) != 1:
            return None, 'multiple_faces' if faces else 'no_face'
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = (faces[0][3:7] * [w, h, w, h]).astype(int)
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
        crop = frame[y1:y2, x1:x2]
        if min(crop.shape[:2], default=0) < 60:
            return None, 'face_too_small'
        points = self.infer(crop, landmarks).reshape(5, 2)
        if not np.isfinite(points).all() or np.any(points < 0) or np.any(points > 1):
            return None, 'invalid_landmarks'
        points = points * [crop.shape[1], crop.shape[0]]
        matrix, _ = cv2.estimateAffinePartial2D(points.astype(np.float32), REFERENCE, method=cv2.LMEDS)
        if matrix is None or not np.isfinite(matrix).all():
            return None, 'alignment_failed'
        aligned = cv2.warpAffine(crop, matrix, (128, 128))
        vector = self.infer(aligned, encoder).reshape(-1)
        norm = np.linalg.norm(vector)
        if vector.shape != (256,) or not np.isfinite(vector).all() or norm < 1e-8:
            return None, 'invalid_embedding'
        return vector / norm, 'ok'


def capture(user, label, validation=False, seconds=15):
    path = state_path(user)
    state = load_state(user) if path.exists() else new_state(user)
    data, labels = templates(state) if validation else (None, None)
    if not validation and len(state['profiles']) >= 16:
        raise ValueError('Maximum 16 profiles')
    if not validation and any(p['label'] == label for p in state['profiles']):
        raise ValueError('Label already enrolled; use a new label')
    pipeline = Pipeline()
    embeddings, similarities, statuses = [], [], {}
    last = 0.0
    print(f'Ready: {label}. Capture for {seconds}s; embeddings only.', flush=True)
    start = time.monotonic()
    try:
        while time.monotonic() - start < seconds:
            embedding, status = pipeline.read()
            statuses[status] = statuses.get(status, 0) + 1
            now = time.monotonic()
            if embedding is None or now - last < 0.7:
                continue
            last = now
            if validation:
                similarity, index = score(embedding, data)
                similarities.append(similarity)
                print(f'{len(similarities):2}: similarity={similarity:.3f}; profile={labels[index]}; '
                      f'{"MATCH" if similarity >= THRESHOLD else "no match"}', flush=True)
            else:
                embeddings.append(embedding.tolist())
                print(f'Sample {len(embeddings)} / 12', flush=True)
            if max(len(embeddings), len(similarities)) >= 12:
                break
    finally:
        pipeline.close()
    print('Frame counts:', json.dumps(statuses), flush=True)
    if validation:
        if len(similarities) < 6:
            raise ValueError('Too few validation samples; nothing saved')
        record = {'label': label, 'scores': similarities, 'timestamp': time.time(),
                  'profile_count': len(state['profiles'])}
        state['validation'].append(record)
        print('Validation match rate:', sum(s >= THRESHOLD for s in similarities), '/', len(similarities))
    else:
        if len(embeddings) < 6:
            raise ValueError('Too few enrollment samples; nothing saved')
        state['profiles'].append({'label': label, 'embeddings': embeddings, 'timestamp': time.time()})
        # Changing enrollment invalidates old held-out validation results.
        state['validation'] = []
    save_json(path, state)
    print('Saved root-only', path, flush=True)


def authenticate(user, active=True, verbose=False):
    config = configparser.ConfigParser()
    config.read(trusted(CONFIG))
    if config.getboolean('core', 'disabled', fallback=False):
        return 12
    state = load_state(user, active=active)
    data, labels = templates(state)
    pipeline = Pipeline()
    gate = MatchGate()
    start = time.monotonic()
    try:
        while time.monotonic() - start < config.getfloat('video', 'timeout', fallback=8):
            embedding, status = pipeline.read()
            if embedding is None:
                # IR-dark frames are expected, but never count as matches.
                if status != 'dark':
                    gate.reset()
                continue
            similarity, index = score(embedding, data)
            now = time.monotonic()
            if verbose:
                print(f'{similarity:.3f} {labels[index]}', flush=True)
            if gate.update(similarity >= THRESHOLD, now):
                if verbose:
                    print('MATCH: multiple frames confirmed', flush=True)
                return 0
        if verbose:
            print('NO MATCH: password fallback', flush=True)
        return 11
    finally:
        pipeline.close()


def promote(user):
    state = load_state(user)
    templates(state)
    validations = state['validation']
    # Deployment scope explicitly accepted by the user: two held-out conditions.
    # This is an operational check, not a false-accept/security calibration.
    if len(state['profiles']) < 5 or len(validations) < 2:
        raise ValueError('Need at least 5 profiles and 2 held-out validation conditions')
    if len({v['label'] for v in validations}) < 2:
        raise ValueError('Validation conditions must have distinct labels')
    for record in validations:
        scores = record['scores']
        if len(scores) < 6 or sum(s >= THRESHOLD for s in scores) / len(scores) < 0.8:
            raise ValueError(f'Validation condition did not reach 80%: {record["label"]}')
    state['deployment_notes'] = {
        'user_accepted_incomplete_validation': True,
        'not_completed': ['separate lighting validation', 'other-person rejection', 'spoof testing'],
        'security_calibrated': False,
    }
    target = state_path(user, active=True)
    save_json(target, state)
    # Unprivileged swaylock must read this account's templates, never modify them.
    os.chown(target, 0, pwd.getpwnam(user).pw_gid)
    os.chmod(target, 0o640)
    print('Activated root-owned, account-readable NPU enrollment; dispatch is a separate step.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['enroll', 'validate', 'test', 'auth', 'check', 'report', 'promote'])
    parser.add_argument('--user', required=True)
    parser.add_argument('--label')
    args = parser.parse_args()
    account = pwd.getpwnam(args.user)
    if os.geteuid() != 0:
        if args.command not in ('auth', 'check') or os.geteuid() != account.pw_uid:
            raise PermissionError('Only own-account authentication is allowed without sudo')
    if args.command in ('auth', 'test'):
        # Hard upper bound includes model startup and potentially stalled capture.
        signal.signal(signal.SIGALRM, lambda *_: sys.exit(12))
        signal.alarm(15)
        return authenticate(args.user, active=args.command == 'auth', verbose=args.command == 'test')
    if args.command in ('enroll', 'validate'):
        if not args.label or len(args.label) > 100:
            raise ValueError('Provide a short descriptive label')
        signal.signal(signal.SIGALRM, lambda *_: sys.exit(12))
        signal.alarm(35)
        capture(args.user, args.label, validation=args.command == 'validate')
    elif args.command == 'report':
        state = load_state(args.user)
        print(json.dumps({'threshold': state['threshold'],
                          'profiles': [(p['label'], len(p['embeddings'])) for p in state['profiles']],
                          'validation': state['validation']}, indent=2))
    elif args.command == 'check':
        state = load_state(args.user, active=True)
        data, _ = templates(state)
        config = configparser.ConfigParser()
        config.read(trusted(CONFIG))
        core = ov.Core()
        if 'NPU' not in core.available_devices:
            raise RuntimeError('NPU unavailable to current account')
        for name in NAMES:
            trusted(MODEL_DIR / f'{name}.xml')
            trusted(MODEL_DIR / f'{name}.bin')
        print(json.dumps({'user': args.user, 'profiles': len(state['profiles']),
                          'embeddings': len(data), 'threshold': THRESHOLD,
                          'npu_available': True,
                          'dispatch_enabled': config.getboolean('npu', 'enabled', fallback=False),
                          'security_calibrated': False}, indent=2))
    elif args.command == 'promote':
        promote(args.user)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(f'Howdy NPU: {exc}', file=sys.stderr)
        sys.exit(12)
