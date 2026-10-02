# Architecture and interfaces

The browser UI, MCP bridge and local HTTP API all use the same SQLite project/task store. A single worker provisions locked files and submits native workflows to an isolated ComfyUI process on `127.0.0.1:8191`. The station uses `127.0.0.1:8765`. Neither service should be exposed to a public network.

The control server and MCP bridge use Python's standard library; the launcher bootstraps a private Python without pip or PATH changes. The engine uses the official portable NVIDIA runtime. The UI uses plain HTML/CSS/JavaScript, so building or running does not require Node/npm. GPU inference is local, with no paid API or account requirement. Downloads contact python.org, GitHub and Hugging Face.

## API

Read endpoints: `/api/health`, `/api/status`, `/api/projects`, `/api/jobs`, `/api/keywords`, `/api/logs?name=engine`.

POST requests require `X-Station-Token`, read locally from `.local/api-token`, and JSON bodies. Tokens are regenerated on server restart. Browsers obtain a same-origin session token; other origins are rejected. This is a single-user local tool, not a multi-user security boundary against other processes on the same machine.

- `/api/projects`: `{id, name, shots: [...]}` (whole-project save; preserve unchanged fields).
- `/api/jobs`: `{project, shot: {id, prompt, profile: "wan13", width:512, height:320, frames:33, fps:16, steps:20, cfg:5, seed:42, positive:[], negative_tags:[], loras:[]}}`.
- `/api/upload`: `{name:"reference.png", content:"base64..."}` → generated local filename; use as `shot.image` with `profile:"wan5"`.
- `/api/setup`: `{profile:"wan13"}` or `wan5`.
- `/api/cancel`: `{id:"job-id"}`.
- `/api/export`: `{jobs:["completed-job-id", ...]}` → MP4 path relative to output.
- `/api/settings`: `{data_root:"absolute path"}`. Selects a workspace, does not move old files.

Tag shape: `{label, text, weight}`; weights 0–2 order and emphasize text, not SD-style conditioning arithmetic. LoRA shape: `{file:"name.safetensors", weight:0.8}`. Only LoRAs for the chosen Wan architecture are compatible. SD character LoRAs are not interchangeable.

Widths/heights must be multiples of 32, between 256 and 832. Frames are `4n+1`, between 9 and 81. Longer works are composed from separately generated shots, not unlimited single-pass video. Same-character continuity and temporal quality are not guaranteed.

## MCP

Launch the workstation first, then run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File <absolute-repo-path>/scripts/start.ps1 -Mcp`. Copy a complete configuration from Settings. Tools cover status, keywords, projects, video jobs, reference upload, cancellation and export. No command execution tool is exposed.

## Tests and packaging

```powershell
& .\.runtime\python\python.exe -I -m unittest discover -s tests -v
node --check web/app.js
```

`scripts/package.ps1` creates a clean source ZIP. `-Offline` adds this installation's verified models and private runtimes, excluding projects, outputs, references, tokens and machine-specific settings. Prepare the desired models first. Offline bundles are large, Windows/NVIDIA-specific, and must retain all third-party notices/source obligations; do not commit them to Git.

Implemented scope: short text/image-conditioned video, native Wan LoRA loading, prompt library, card storyboard, version history, local job queue and silent MP4 concatenation. Not included: LoRA training, speech/music, automated story planning, multi-track timeline, lip sync, motion brushes, FramePack/VACE/Manim/LightX2V or cloud services. This first version is not feature/quality parity with Higgsfield.
