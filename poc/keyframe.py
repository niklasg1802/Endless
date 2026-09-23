"""Generate or edit a keyframe image via an OpenRouter image model.

Usage:
    python3 poc/keyframe.py <name> <prompt_file> [--image input.jpg ...] [--model google/gemini-3.1-flash-image]

Input images are sent along with the prompt (for editing / as references).
Writes poc/out/<name>.png (plus _2, _3 ... if the model returns several images).
"""

import argparse
import base64
import json
import pathlib
import sys

from h3_cloud import OUT, api_key, image_part, request

API = "https://openrouter.ai/api/v1/chat/completions"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("name")
    p.add_argument("prompt_file")
    p.add_argument("--image", action="append", default=[])
    p.add_argument("--model", default="google/gemini-3.1-flash-image")
    args = p.parse_args()

    content = [{"type": "text", "text": pathlib.Path(args.prompt_file).read_text().strip()}]
    content += [image_part(i) for i in args.image]
    payload = {
        "model": args.model,
        "messages": [{"role": "user", "content": content}],
        "modalities": ["image", "text"],
        "image_config": {"aspect_ratio": "16:9"},
    }

    OUT.mkdir(parents=True, exist_ok=True)
    resp = request(API, api_key(), payload)
    msg = resp["choices"][0]["message"]
    images = msg.get("images") or []
    if not images:
        sys.exit(f"no image returned. text: {msg.get('content')!r} finish: {resp['choices'][0].get('finish_reason')}")

    for i, img in enumerate(images, 1):
        data = img["image_url"]["url"].split(",", 1)[1]
        path = OUT / (f"{args.name}.png" if i == 1 else f"{args.name}_{i}.png")
        path.write_bytes(base64.b64decode(data))
        print(f"saved {path.relative_to(OUT.parent.parent)}")
    print(f"cost={resp.get('usage', {}).get('cost')} text={(msg.get('content') or '')[:200]!r}")


if __name__ == "__main__":
    main()
