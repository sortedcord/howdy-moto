# System inventory (sanitized, recorded 2026-11-13)

No serial numbers, machine IDs, Wi-Fi credentials, stored passwords, or face
embeddings are included. This is system-specific, not a generic distribution.

| Component | Observed configuration |
|---|---|
| OS | Arch Linux, kernel `7.2.14-arch1-1` |
| CPU | Intel Core Ultra 5 225H, 14 logical CPUs |
| GPU | Intel Arc Pro 130T/140T integrated, PCI `8086:7d51` |
| NPU | Intel Core Ultra 200H/200V NPU, PCI `8086:7d1d`; OpenVINO device `3720` |
| NPU kernel module | `intel_vpu` |
| NPU device | `/dev/accel/accel0` |
| IR capture | `/dev/v4l/by-path/<your-ir-camera-path>` |
| IR format | GREY, 640×360, 15/30 FPS; configured 30 FPS |
| IR illumination | Alternating dark/illuminated frames observed; dark frames skipped |
| Desktop | Niri Wayland, launched through GDM |
| Login/lock | GDM `gdm-password`; swaylock with `pam_howdy.so` |
| Secret service | GNOME Keyring, `org.freedesktop.secrets` |
| Account | Login account, UID/GID 1000 (username omitted) |
| Root filesystem | ext4 directly on an NVMe partition; no LUKS layer observed |

## Package versions

```
howdy-git r592.d3ab993-1
openvino 2026.4.1-1
python-openvino 2026.4.1-1
openvino-intel-npu-plugin 2026.4.1-1
intel-npu-driver 1.38.0-1
intel-npu-compiler 2026.38-1
level-zero-loader 1.34.0-1
gnome-keyring 1:51.1-1
libsecret 0.21.8.2-1
pam 1.7.3-1
python-gobject 3.58.1-1
```

## Benchmarks previously measured

Same three-model aligned pipeline, real IR capture, 12 seconds each:

| Metric | CPU-only | NPU |
|---|---:|---:|
| Frames / embeddings | 177 / 89 | 177 / 89 |
| Process CPU time | 18.108 s | 0.375 s |
| Mean CPU usage (one core = 100%) | 150.5% | 3.1% |
| Detection | 25.9 ms | 20.6 ms |
| Alignment + embedding | 8.4 ms | 4.5 ms |

Approximately 98% less CPU work during these runs. Model initialization excluded.
These compare OpenVINO CPU/NPU execution, not the original dlib HOG pipeline.

## Sources inspected

- Howdy commit `d3ab99382f88f043d15f15c1450ab69433892a1c`:
  https://github.com/boltgolt/howdy
- Third-party GPU patch (reference only; not blindly installed):
  https://github.com/dys0re/howdy-ir-openvino
- Open Model Zoo model documentation:
  https://github.com/openvinotoolkit/open_model_zoo/tree/master/models/intel
- GNOME Keyring source checked for private D-Bus password-change/unlock behavior,
  commit `8561976b6b4662330caeb16c921472a89e891ed1`:
  https://github.com/GNOME/gnome-keyring
- GNOME PAM documentation:
  https://wiki.gnome.org/Projects/GnomeKeyring/Pam
- Intel OpenVINO NPU documentation:
  https://docs.openvino.ai/2025/openvino-workflow/running-inference/inference-devices-and-modes/npu-device.html
