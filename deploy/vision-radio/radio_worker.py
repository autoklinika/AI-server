#!/usr/bin/env python3
"""Fixed isolated RADIO job. No shell, URL, dynamic model or Gateway credential.

Only the supervisor may write control files. Worker telemetry never authorizes
lease release: the parent must independently prove service/cgroup closure.
"""
from __future__ import annotations
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time

MODEL_ROOT = Path('/srv/ai-data/evaluation/vision-pcb-envs')
RUNTIME = MODEL_ROOT / 'anomalyvfm-radio-rocm714-py311'
CACHE = MODEL_ROOT / 'anomalyvfm-radio-pilot-20261016/hf_cache'
WEIGHTS = CACHE / ('models--MaticFuc--anomalyvfm_radio/snapshots/'
    '17654e763c8fae5ae1c44e2ec421a427783d6196/model.safetensors')
WEIGHT_SHA = '50a219ba436ed656ad3c0405f9e81df8ad00b2e715c98be66d7e2edb62a83a37'
IMAGE = Path('/srv/ai-data/evaluation/vision-pcb-datasets/visa-20220922/extracted/pcb2/Data/Images/Normal/0000.JPG')
IMAGE_SHA = 'b3f01fc1c1bd43df2c5a1afa63348097f7ecbcc9ebe2fd43bed6f2d074531a37'
IMAGE_ID = 'visa-pcb2-normal-0000'
STATE = Path('/var/lib/ai-platform-radio')


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def write_once(path, value):
    content = json.dumps(value, allow_nan=False, sort_keys=True) + '\n'
    temp = path.with_name(path.name + '.tmp')
    with temp.open('x') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(temp, path)
    temp.unlink()


def wait_control(folder, name, deadline):
    path = folder / name
    while time.monotonic() < deadline:
        if path.is_file():
            info = path.stat()
            if info.st_uid != 0 or info.st_mode & 0o022:
                raise RuntimeError('untrusted control file')
            if path.read_text() != '1\n':
                raise RuntimeError('invalid control message')
            return
        time.sleep(.1)
    raise TimeoutError('supervisor control timeout')


def run_inference(folder):
    if Path(sys.prefix).resolve() != RUNTIME:
        raise RuntimeError('incorrect fixed runtime')
    if sha(WEIGHTS) != WEIGHT_SHA or sha(IMAGE) != IMAGE_SHA:
        raise RuntimeError('pinned model/image changed')
    for key, value in {'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
        'HF_HUB_CACHE': str(CACHE), 'HF_HUB_DISABLE_TELEMETRY': '1',
        'OMP_NUM_THREADS': '2', 'MKL_NUM_THREADS': '2', 'HOME': str(folder / 'data'),
        'XDG_CACHE_HOME': str(folder / 'data/cache')}.items():
        os.environ[key] = value
    import torch
    import numpy as np
    from PIL import Image
    from torchvision.transforms import v2
    from anomalib import PrecisionType
    from anomalib.models.image.anomalyvfm.torch_model import AnomalyVFMModel
    # The bundled fixed ABI helper checks full BDF without running matmul.
    import ctypes
    if torch.version.hip is None or torch.cuda.device_count() != 1:
        raise RuntimeError('single ROCm GPU required')
    props = torch.cuda.get_device_properties(0)
    if props.gcnArchName.split(':')[0] != 'gfx1150':
        raise RuntimeError('wrong GPU architecture')
    lib = Path(torch.__file__).resolve().parents[1] / '_rocm_sdk_core/lib/libamdhip64.so.7'
    hip = ctypes.CDLL(str(lib))
    function = hip.hipDeviceGetPCIBusId
    function.argtypes = (ctypes.POINTER(ctypes.c_char), ctypes.c_int, ctypes.c_int)
    function.restype = ctypes.c_int
    bus = ctypes.create_string_buffer(64)
    if function(bus, 64, 0) != 0 or bus.value.decode('ascii').lower() != '0000:c6:00.0':
        raise RuntimeError('wrong physical GPU')
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.cuda.set_per_process_memory_fraction(min(1, 12 * (1 << 30) / props.total_memory))
    started = time.monotonic()
    model = AnomalyVFMModel()
    model.precision = PrecisionType.FLOAT32
    model.to('cuda').eval()
    transform = v2.Compose([v2.ToImage(), v2.Resize((768, 768), antialias=True),
                           v2.ToDtype(torch.float32, scale=True)])
    with Image.open(IMAGE) as image:
        tensor = transform(image.convert('RGB')).unsqueeze(0).to('cuda')
    with torch.inference_mode():
        score, mask = model(tensor)
        torch.cuda.synchronize()
    value = float(score.detach().cpu().reshape(-1)[0])
    array = mask.detach().cpu().numpy()[0, 0].astype('float32')
    if (score.numel() != 1 or not math.isfinite(value) or not 0 <= value <= 1
            or array.shape != (768, 768) or not np.isfinite(array).all()
            or float(array.min()) < 0 or float(array.max()) > 1):
        raise RuntimeError('invalid RADIO output')
    output = folder / 'data/anomaly.map.npy'
    with output.open('xb') as stream:
        np.save(stream, array, allow_pickle=False)
        stream.flush()
        os.fsync(stream.fileno())
    write_once(folder / 'data/result.json', {
        'schema': 1, 'image_id': IMAGE_ID, 'execution_kind': 'GPU_INFERENCE',
        'model': 'anomalyvfm-radio', 'weights_sha256': WEIGHT_SHA,
        'image_sha256': IMAGE_SHA, 'image_score': value,
        'map_shape': [768, 768], 'map_sha256': sha(output),
        'inference_and_load_seconds': time.monotonic() - started,
        'pci_bdf': '0000:c6:00.0', 'worker_local_sync': True,
    })
    # Retain the actual context until the supervisor has observed this worker
    # as the GPU owner, then release and exit naturally within the same cgroup.
    wait_control(folder, 'release', time.monotonic() + 100)
    del tensor, score, mask, model, array
    gc.collect()
    torch.cuda.empty_cache()
    torch.cuda.synchronize()


def main():
    if len(sys.argv) != 2 or re.fullmatch(r'[0-9a-f]{32}', sys.argv[1]) is None:
        return 2
    if os.getuid() != 994:
        raise RuntimeError('fixed ai-vision UID required')
    folder = STATE / 'sessions' / sys.argv[1]
    write_once(folder / 'data/ready.json', {'pid': os.getpid(), 'uid': os.getuid()})
    wait_control(folder, 'execute', time.monotonic() + 100)
    run_inference(folder)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
