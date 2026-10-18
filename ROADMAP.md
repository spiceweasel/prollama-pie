# ROADMAP.md 

## FEATURE: Per device binary specification

        To address an important architectural consideration whereby a single llama-server binary file is utilized for all hardware types, a more flexible consideration must be made.

        The current implementation uses a single global binary setting.

        That means the configuration file is suitable as a common example for different hardware platforms, but the selected llama-server executable must support the backend being used.

        For greater flexibility, it is recommended to eventually support per-profile binary overrides:
        "rocm-0": {
        "description": "ROCm GPU 0",
        "binary": "/opt/llama.cpp/build-rocm/bin/llama-server",
        "env": {
            "HIP_VISIBLE_DEVICES": "0"
        },
        "gpu_ids": [0]
        },
        "cuda-0": {
        "description": "CUDA GPU 0",
        "binary": "/opt/llama.cpp/build-cuda/bin/llama-server",
        "env": {
            "CUDA_VISIBLE_DEVICES": "0"
        },
        "gpu_ids": [0]
        }

        This override is a proposed enhancement, not currently supported yet.

        It would allow a single installation of prollama-pie to manage separate CPU, ROCm, and CUDA builds without switching the global executable.

        We should also make the GPU resource manager backend-aware. Currently, gpu_ids uses numeric indices, so GPU 0 under ROCm and GPU 0 under CUDA could be confused when both vendors are installed on the same host.

        I recommend making per-profile binary selection and backend-aware GPU identification part of the next version. That would keep hardware configuration simple while supporting genuinely heterogeneous systems.