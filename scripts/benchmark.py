"""Synthetic inference test only; never reads camera or modifies Howdy."""
from pathlib import Path
import json
import time
import numpy as np
import openvino as ov


def main():
    base = Path(__file__).resolve().parents[1]
    core = ov.Core()
    print('OpenVINO:', ov.__version__, 'devices:', core.available_devices, flush=True)
    results = []
    for name in ('face-detection-adas-0001', 'face-reidentification-retail-0095'):
        model = core.read_model(base / 'models' / f'{name}.xml')
        data = np.zeros(list(model.input().shape), dtype=np.float32)
        for device in ('CPU', 'NPU'):
            row = {'model': name, 'device': device}
            try:
                start = time.perf_counter()
                compiled = core.compile_model(model, device)
                row['compile_seconds'] = time.perf_counter() - start
                row['execution_devices'] = compiled.get_property('EXECUTION_DEVICES')
                request = compiled.create_infer_request()
                start = time.perf_counter()
                request.infer({0: data})
                row['first_inference_ms'] = (time.perf_counter() - start) * 1000
                for _ in range(5):
                    request.infer({0: data})
                wall = time.perf_counter()
                cpu = time.process_time()
                for _ in range(100):
                    output = request.infer({0: data})
                row['cpu_ms_per_inference'] = (time.process_time() - cpu) * 10
                row['wall_ms_per_inference'] = (time.perf_counter() - wall) * 10
                row['finite_output'] = all(bool(np.isfinite(v).all()) for v in output.values())
            except Exception as exc:
                row['error'] = str(exc)
            results.append(row)
            print(json.dumps(row, indent=2), flush=True)
    print('Synthetic inputs only: not recognition accuracy or full unlock latency.')
    # Print results rather than write files as root in the user's directory.


if __name__ == '__main__':
    main()
