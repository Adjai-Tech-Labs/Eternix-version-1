import os

from huggingface_hub import hf_hub_download


def download_model(repo_id, filename, local_dir):
    print(f"Downloading {filename} from {repo_id}...")
    try:
        path = hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            local_dir=os.path.expanduser(local_dir),
            local_dir_use_symlinks=False,
        )
        print(f"Downloaded to: {path}")
        return True
    except OSError as e:
        print(f"Error: {e}")
        return False


if __name__ == "__main__":
    models = [
        ("Qwen/Qwen3-4B-GGUF", "Qwen3-4B-Q4_K_M.gguf", "~/AI/ETERNIX/models/qwen3-4b"),
        ("Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF", "Qwen2.5-Coder-1.5B-Instruct-Q4_K_M.gguf", "~/AI/ETERNIX/models/qwen-coder-1.5b"),
        ("Qwen/Qwen3-VL-2B-Instruct-GGUF", "Qwen3VL-2B-Instruct-Q4_K_M.gguf", "~/AI/ETERNIX/models/qwen-vl-2b"),
        ("Qwen/Qwen3-VL-2B-Instruct-GGUF", "mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf", "~/AI/ETERNIX/models/qwen-vl-2b"),
        ("Qwen/Qwen3-Embedding-0.6B-GGUF", "Qwen3-Embedding-0.6B-Q8_0.gguf", "~/AI/ETERNIX/models/qwen3-embedding-0.6b"),
    ]

    for repo_id, filename, local_dir in models:
        download_model(repo_id, filename, local_dir)