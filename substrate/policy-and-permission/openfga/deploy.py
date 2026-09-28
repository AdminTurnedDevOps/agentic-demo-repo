"""Apply the adapter manifest with the image built by the lab operator."""

import argparse
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True, help="pullable image reference, preferably digest-pinned")
    args = parser.parse_args()
    if "/" not in args.image or any(c.isspace() for c in args.image):
        parser.error("--image must be a pullable, fully-qualified image reference")
    source = (Path(__file__).parent / "auth.yaml").read_text()
    manifest = source.replace("ADAPTER_IMAGE_PLACEHOLDER", args.image)
    subprocess.run(["kubectl", "apply", "-f", "-"], input=manifest, text=True, check=True)


if __name__ == "__main__":
    main()
