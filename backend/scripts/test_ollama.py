import json
import os
import sys
import time
import urllib.error
import urllib.request


def test_ollama() -> None:
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
    ollama_model = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:3b")

    endpoint = f"{ollama_url}/api/generate"
    payload = {
        "model": ollama_model,
        "prompt": "Respond with exactly the word 'ready' and nothing else.",
        "stream": False,
    }

    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    print(f"Connecting to Ollama at {ollama_url} (model: {ollama_model})...")
    start_time = time.perf_counter()

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            duration = time.perf_counter() - start_time
            body = json.loads(response.read().decode("utf-8"))
            reply = body.get("response", "").strip()

            print(f"Response: {reply}")
            print(f"Time taken: {duration:.2f}s")
    except urllib.error.HTTPError as e:
        print(f"Error: Ollama API returned HTTP status {e.code}.")
        print(f"Details: {e.read().decode('utf-8', errors='replace')}")
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Error: Could not connect to Ollama at {ollama_url}.")
        print(f"Details: {e.reason}")
        print("Please ensure Ollama is installed and running (`ollama serve`).")
        sys.exit(1)
    except TimeoutError:
        print(f"Error: Connection to Ollama at {ollama_url} timed out.")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Failed to parse JSON response from Ollama: {e}")
        sys.exit(1)


if __name__ == "__main__":
    test_ollama()
