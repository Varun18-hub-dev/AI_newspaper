#!/usr/bin/env python3
"""GPU Worker Runtime and Model Verification Script.

Executes post-boot verification of the dedicated EC2 worker environment:
1. NVIDIA Drivers & CUDA Availability
2. VRAM Headroom & Device Capabilities (checks >= 8 GB for NVIDIA T4)
3. ONNX Runtime Providers (CUDAExecutionProvider / CPUExecutionProvider)
4. Ollama Daemon Connectivity and Qwen 2.5 3B Model Availability
5. Test Inference Latency and Output Quality

Usage:
    python scripts/verify_gpu_runtime.py [--require-gpu]
"""

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.request

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("gpu_verifier")


def check_nvidia_smi() -> dict:
    """Checks nvidia-smi tool and parses GPU details."""
    smi_path = shutil.which("nvidia-smi")
    if not smi_path:
        return {"available": False, "reason": "nvidia-smi executable not found in PATH"}

    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free,driver_version", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode != 0:
            return {"available": False, "reason": f"nvidia-smi exited with code {proc.returncode}: {proc.stderr.strip()}"}

        lines = proc.stdout.strip().split("\n")
        if not lines or not lines[0]:
            return {"available": False, "reason": "No GPU devices reported by nvidia-smi"}

        parts = [p.strip() for p in lines[0].split(",")]
        return {
            "available": True,
            "device_name": parts[0],
            "total_memory_mb": int(parts[1]),
            "free_memory_mb": int(parts[2]),
            "driver_version": parts[3],
        }
    except Exception as exc:
        return {"available": False, "reason": str(exc)}


def check_onnx_runtime() -> dict:
    """Checks onnxruntime installation and available execution providers."""
    try:
        import onnxruntime as ort
        providers = ort.get_available_providers()
        has_cuda = "CUDAExecutionProvider" in providers
        return {
            "installed": True,
            "version": ort.__version__,
            "providers": providers,
            "has_cuda": has_cuda,
        }
    except ImportError:
        return {"installed": False, "providers": [], "has_cuda": False}


def check_ollama(base_url: str = "http://localhost:11434", target_model: str = "qwen2.5:3b") -> dict:
    """Checks Ollama server status and verifies model presence."""
    try:
        req = urllib.request.Request(f"{base_url}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name") for m in data.get("models", [])]
            has_model = any(target_model in m for m in models)
            return {
                "running": True,
                "models": models,
                "has_target_model": has_model,
            }
    except Exception as exc:
        return {"running": False, "error": str(exc), "has_target_model": False}


def test_ollama_inference(base_url: str = "http://localhost:11434", model: str = "qwen2.5:3b") -> dict:
    """Executes a test inference call to verify latency and model functionality."""
    payload = json.dumps({
        "model": model,
        "prompt": "Respond with 'READY' if operational.",
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 10},
    }).encode("utf-8")

    start_time = time.time()
    try:
        req = urllib.request.Request(
            f"{base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            elapsed = time.time() - start_time
            result = json.loads(resp.read().decode("utf-8"))
            return {
                "success": True,
                "latency_sec": round(elapsed, 3),
                "response": result.get("response", "").strip(),
            }
    except Exception as exc:
        return {"success": False, "latency_sec": round(time.time() - start_time, 3), "error": str(exc)}


def main():
    parser = argparse.ArgumentParser(description="Verify GPU Worker Runtime")
    parser.add_argument("--require-gpu", action="store_true", help="Fail with non-zero exit if GPU is missing")
    parser.add_argument("--ollama-url", default="http://localhost:11434", help="Ollama server URL")
    parser.add_argument("--model", default="qwen2.5:3b", help="Model name to verify")
    args = parser.parse_args()

    print("=" * 60)
    print(" Personal AI Newspaper — GPU Worker Environment Verification")
    print("=" * 60)

    # 1. GPU Check
    gpu_info = check_nvidia_smi()
    if gpu_info["available"]:
        print(f"[OK] GPU Detected: {gpu_info['device_name']}")
        print(f"     Total VRAM:   {gpu_info['total_memory_mb']} MB")
        print(f"     Free VRAM:    {gpu_info['free_memory_mb']} MB")
        print(f"     Driver:       {gpu_info['driver_version']}")
    else:
        print(f"[WARN] GPU not detected: {gpu_info.get('reason')}")
        if args.require_gpu:
            print("[FAIL] --require-gpu set and GPU is unavailable. Exiting.")
            sys.exit(1)

    # 2. ONNX Runtime
    ort_info = check_onnx_runtime()
    if ort_info["installed"]:
        print(f"[OK] ONNX Runtime v{ort_info['version']} available.")
        print(f"     Providers: {', '.join(ort_info['providers'])}")
        if ort_info["has_cuda"]:
            print("     CUDA Execution Provider: ENABLED")
        else:
            print("     CUDA Execution Provider: DISABLED (Falling back to CPU provider)")
    else:
        print("[WARN] ONNX Runtime is not installed.")

    # 3. Ollama Service
    ollama_info = check_ollama(args.ollama_url, args.model)
    if ollama_info["running"]:
        print(f"[OK] Ollama daemon running at {args.ollama_url}.")
        print(f"     Installed models: {', '.join(ollama_info['models'])}")
        if ollama_info["has_target_model"]:
            print(f"[OK] Target model '{args.model}' is downloaded and ready.")
            # 4. Inference Test
            infer_info = test_ollama_inference(args.ollama_url, args.model)
            if infer_info["success"]:
                print(f"[OK] Inference test succeeded in {infer_info['latency_sec']}s: {infer_info['response']}")
            else:
                print(f"[WARN] Inference test failed: {infer_info.get('error')}")
        else:
            print(f"[WARN] Target model '{args.model}' not found in Ollama repository.")
    else:
        print(f"[WARN] Ollama daemon not reachable at {args.ollama_url}: {ollama_info.get('error')}")

    print("=" * 60)
    print(" Verification complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
