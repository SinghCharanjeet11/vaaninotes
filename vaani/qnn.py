"""Create ONNX Runtime sessions on the Hexagon NPU.

Supports both packaging styles of the QNN execution provider:
* onnxruntime-qnn >= 2.0 — a *plugin* EP that must be registered with
  ``ort.register_execution_provider_library`` and bound to the NPU device.
* onnxruntime-qnn 1.x — QNN built into onnxruntime, selected with ``providers=[...]``.
"""

from __future__ import annotations

from functools import lru_cache

EP_NAME = "QNNExecutionProvider"
PERF_OPTIONS = {"htp_performance_mode": "burst"}


@lru_cache(maxsize=1)
def _plugin_devices():
    """Register the plugin EP once; return its NPU devices (empty list if none)."""
    import onnxruntime as ort

    try:
        import onnxruntime_qnn as qnn_ep
    except ImportError:
        return None
    try:
        ort.register_execution_provider_library(EP_NAME, qnn_ep.get_library_path())
    except Exception as e:  # already registered, or no NPU driver on this machine
        if "already" not in str(e).lower():
            return []
    devices = [d for d in ort.get_ep_devices() if d.ep_name == EP_NAME]
    npu = [d for d in devices if "NPU" in str(d.device.type).upper()]
    return npu or devices


def available() -> bool:
    try:
        import onnxruntime as ort
    except ImportError:
        return False
    devices = _plugin_devices()
    if devices:
        return True
    return EP_NAME in ort.get_available_providers()


def session(model_path: str):
    import onnxruntime as ort

    opts = ort.SessionOptions()
    devices = _plugin_devices()
    if devices:
        import onnxruntime_qnn as qnn_ep

        base = {"backend_path": qnn_ep.get_qnn_htp_path()}
        try:
            opts.add_provider_for_devices(devices, {**base, **PERF_OPTIONS})
            return ort.InferenceSession(model_path, sess_options=opts)
        except Exception:
            opts = ort.SessionOptions()
            opts.add_provider_for_devices(devices, base)
            return ort.InferenceSession(model_path, sess_options=opts)
    return ort.InferenceSession(
        model_path, opts,
        providers=[(EP_NAME, {"backend_path": "QnnHtp.dll", **PERF_OPTIONS})],
    )
