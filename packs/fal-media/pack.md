<!-- Copyright 2026 Tharwat Abdul-Malik. Part of agent-kit (MIT License). -->
# Pack: fal-media

An opt-in extra. It installs third-party fal.ai skills at `.claude/skills/<name>/`, fetched from GitHub at the
commit pinned in `pack.json` and checked against its sha256; the kit never copies them. It extends no core command
and has no facts of its own.

| Skill | Use it for |
|---|---|
| `genmedia` | Running fal models from a terminal with the genmedia CLI. The other skills call it |
| `fal-media` | Generating media through a connected fal MCP server (model choice, schemas, pricing, uploads) |
| `fal-workflow` | Writing fal workflow JSON, or chaining several genmedia jobs |
| `fal-video-generation` | One video clip: animate an image, extend, restyle or upscale |
| `fal-audio-generation` | Voiceover, dubbing, transcription, sound effects and music |
| `fal-prompting` | Prompts tuned to the chosen fal model family |
| `fal-models-catalog` | Comparing fal models by modality and role |
| `fal-recipes` | Ready pipelines: try-on, restoration, lip sync |
| `fal-shot-craft` | Writing or improving one video shot prompt |

## Notes

- **`FAL_KEY`** is never put on a command line. Every call is billed to that key's account.
- Without a fal MCP server, use `genmedia` instead of the `fal-media` skill.
