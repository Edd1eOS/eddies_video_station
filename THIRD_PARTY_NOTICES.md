# Third-party components

The MIT license applies only to this repository's original launcher, UI and integration code. Components downloaded at runtime retain their own licenses; no ownership of third-party code or weights is claimed.

- ComfyUI 0.37.0: [GPL-3.0 source and license](https://github.com/Comfy-Org/ComfyUI/tree/v0.37.0). Executed as a separate local process through its HTTP API. Official portable distribution includes Python, PyTorch, FFmpeg-related packages and other dependencies with their own notices. Preserve those licenses when redistributing an offline bundle.
- Python 3.12.10: [PSF license](https://docs.python.org/3.12/license.html). Downloaded from python.org, SHA-256 checked.
- Wan 2.1: [official source/model license](https://github.com/Wan-Video/Wan2.1), Apache-2.0. [Comfy packaging](https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged).
- Wan 2.2: [official source/model license](https://github.com/Wan-Video/Wan2.2), Apache-2.0. [Comfy packaging](https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged).
- UMT5 XXL text encoder: [upstream model](https://huggingface.co/google/umt5-xxl), Apache-2.0. Runtime downloads a quantized Comfy-Org packaging.

Exact model revisions, sizes and SHA-256 digests are in `configs/models.json`. Model licenses do not grant rights to third-party images, likenesses, brands or copyrighted characters. Users must review licenses of separately imported LoRAs and other assets.

Visual direction was supplied by the user from [Claymorphism Card (Figma Community)](https://www.figma.com/design/VikxYFBCYo3UuDsdBJvRz7/Claymorphism-Card--Community-?node-id=0-1). No Figma files, illustrations or component assets are redistributed; the interface is original HTML/CSS.
