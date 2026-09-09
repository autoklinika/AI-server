# Hermes / LTX-2.3 — Stage30 I2V Quality

Branch: `feat/hermes-i2v-quality-stage30`

Base production commit: `8ea1da0` (Stage29).

## Safety boundary

Stage30 is developed only on the feature branch. It does not change production `main`.
Stage29 remains the known-good baseline and must stay deployable.

Unchanged:
- Hermes deterministic routing model
- Telegram delivery behavior
- Qwen3.6 model
- LTX-2.3 22B
- `/foto`
- T2V graph, sampler, CFG and sigmas
- 1–6 s durations at 24 fps
- Stage29 `VAEDecodeTiled`: 512 / 64 / temporal 32 / temporal overlap 8
- ventilation system

## Stage30 changes — I2V only

### 1. Deterministic high-quality input resize

Before `LTXVPreprocess`, Stage30 inserts core ComfyUI `ImageScale`:

- `upscale_method=lanczos`
- `crop=center`
- target = render resolution

This removes dependence on the implicit bilinear resize inside
`LTXVImgToVideoInplace`.

For HQ, Stage30 builds a separate 1280×768 Lanczos reference before the
second image anchor instead of allowing the node to implicitly bilinear-scale
the 640×384 reference.

### 2. Lower LTX image preprocessing compression

Stage29:
- `img_compression=25`

Stage30 default:
- `img_compression=18`

The value remains exposed as a CLI A/B parameter.

### 3. Gentler first image anchor

Stage30 defaults:

Standard I2V:
- first anchor = `0.85`

HQ I2V:
- first anchor = `0.70`
- post-upscale reinjection = `1.00`

This keeps the strong HQ reference anchor while reducing the abrupt
first-frame-to-motion transition in the first generation stage.

The values are explicit A/B parameters; they are not coupled to the user
motion profile.

### 4. Dedicated conservative Qwen compiler for I2V

T2V delegates to the Stage29 prompt compiler unchanged.

For I2V, Qwen is instructed that:
- the starting image is authoritative for appearance
- it must describe temporal change, not redesign the image
- camera is locked by default
- camera movement must never be invented
- at most one simple camera move is allowed if explicitly requested
- geometry, identity, colors and scene topology are preserved
- one primary action is preferred
- contradictory instructions such as an orbit plus a pixel-identical
  background are forbidden

Qwen temperature for Stage30 I2V is `0.05`.

### 5. Motion profiles

Explicit Telegram control tokens:

- `motion=subtle`
- `motion=normal`
- `motion=strong`

Polish aliases:
- `ruch=lekki`
- `ruch=normalny`
- `ruch=mocny`

Default = `normal`.

Motion level changes the prompt policy only. It does not silently alter
LTX image-anchor strength.

Example:

```text
/wideo 4s motion=subtle robot delikatnie podnosi prawą rękę
```

## Controlled A/B test order

Use the same input image, user prompt, duration and seed.

1. Stage29 baseline: compression 25 / strength 1.00
2. Stage30 compression only: compression 18 / strength 1.00
3. Stage30 compromise: compression 18 / strength 0.85
4. Stage30 official-like first anchor: compression 18 / strength 0.70

Only after the workflow comparison should prompt-compiler effects be compared.

## Acceptance criteria

A Stage30 candidate is better only if it improves most of:

- subject/face/object identity
- rigid geometry
- color stability
- background stability
- reduced morphing/drift
- natural subject motion
- user-requested motion compliance

without regressing:
- successful 4 s and 6 s single renders
- HQ I2V
- tiled VAE OOM protection
- deterministic Telegram routing
