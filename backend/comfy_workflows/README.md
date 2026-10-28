# Comfy Cloud workflows (API format)

Exported 2026-10-25 from Comfy Cloud (workspace of hertzstudio.ksa) after a bake-off on
shot 3-2 of order `4124786c` (Yaman + father + white horse, beach at sunset).
The app stays the orchestrator and assembler; Comfy only replaces the fal calls for
**shot keyframes** and **shot clips**. Sheets stay on GPT Image 2 (open models simplified
the face too much); text, narration and review stay on fal.

| File | Replaces | Model | Measured (RTX PRO 6000) |
|---|---|---|---|
| `keyframe_qwen21_api.json` | GPT Image 2 high keyframes ($0.17) | Qwen Image 2.1 Edit, 40 steps, 1536x864 | ~17-21 s GPU, ~$0.04 |
| `clip_wan22_api.json` | Kling v3 pro / 2.5 turbo clips | Wan 2.2 I2V 14B + lightx2v 4-step, 1280x720, RIFE x3 -> 24 fps | ~80 s GPU per 5 s clip, ~$0.15 |
| `clip_wan22_flf_api.json` | (2026-10-28) the same clip pinned between its start and its checked end picture | `WanFirstLastFrameToVideo`, `{{end_image}}` on node 98 | same as above |
| `sheet_qwen21_api.json` | (2026-10-28) a GPT sheet's big head made the right size for the age | the keyframe workflow at 1024x1536 | ~12 s GPU, ~$0.02 |

Cost basis: Comfy Cloud plan credits, 0.39 credits/GPU-second, ~211 credits per USD.
A Comfy API deployment bills RTX PRO 6000 at $3.49/h (about half of plan credits).

## Calling them

1. Upload each input image: `POST /api/upload/image` (multipart field `image`) -> use the returned `name`.
2. Fill the placeholders below in a copy of the JSON.
3. `POST https://cloud.comfy.org/api/prompt` with body `{"prompt": <filled json>}` and header `X-API-Key`.
   Returns `prompt_id`.
4. Poll `GET /api/jobs/{prompt_id}` until `status == "completed"`; outputs are under `outputs["461"].images`
   (keyframe) or `outputs["108"]` (clip).
5. Download `GET /api/view?filename=<filename>&subfolder=<subfolder>&type=output`.

All four calls were verified from the Comfy Cloud page session on 2026-10-25 (the keyframe JSON was run
end to end through `/api/prompt`). Server-to-server calls use the API key header (paid plan).

The app calls them through `services/ai/comfy.py` (`upload`, `submit`, `wait`, `download`, `run`). What the
API actually answers, as seen with the key on 2026-10-25:
- Job times (`create_time`, `execution_start_time`, `execution_end_time`) are in **ms**, not the seconds the
  docs say. `comfy.gpu_seconds(job)` handles both.
- A clip is listed under `outputs["108"].images` too, with `"animated": [true]`.
- `/api/view` answers **302** to a signed Google Storage link; it is fetched without the API key.
- Failed jobs carry `execution_error.exception_type`; `InsufficientFundsError` / `InactiveSubscriptionError`
  mean no credit. At submit, **402** = insufficient credits and **429** = "User has not paid" (OpenAPI).
  Both lock the engine like fal's balance; the raw answer is kept in `engine_health` (`last_error`).
- Free balance read: `GET /api/billing/usage/timeseries?months=1` → `summary.balance.amount_cents` (cents,
  despite the `_micros` twin field). Used by the key test and the engine probe.
- One real keyframe through the adapter (1 reference, 40 steps): 26 s wall, 12.2 s GPU ≈ $0.023.

## Placeholders

`clip_wan22_api.json`
- `{{start_image}}` node `97` - the shot keyframe (uploaded name)
- `{{motion_prompt}}` node `129:93` - `shot_pipeline.motion_prompt(...)` (cast lock, physics, no text)
- `{{seed}}` node `129:86` - int
- `{{duration_seconds}}` node `129:161` - int seconds; frames = 16*d+1 (always 4n+1). 5 s covers one line;
  use 6-7 for longer lines instead of Kling's 5/10 s rounding.
- `{{output_prefix}}` node `108`
- The 4-step LoRA runs at CFG 1, so the negative prompt (node `129:89`) has no effect; the guards must
  stay in the positive prompt (they already do in `motion_prompt`).

`keyframe_qwen21_api.json`
- `{{ref_1}}`..`{{ref_4}}` nodes `470, 475, 502, 503` -> `images.image_1..4` of node `459:474`.
  Up to 10 refs: add a `LoadImage` node per extra ref and set `images.image_N` on `459:474`;
  delete unused LoadImage nodes and their `images.image_N` keys.
  Order = the `<imageN>` numbering used in the prompt.
- `{{scene_prompt}}` node `459:474`
- `{{seed}}` node `459:458`
- `{{output_prefix}}` node `461`
- Size is fixed by node `459:456` (1536x864, `custom_size` switch on). Prompt enhancer removed on purpose.

## Scene prompt template (code builds it; nothing story-specific is hard-coded)

```
Create a brand-new 16:9 children's storybook illustration using the people and objects from the
reference images (a new scene, not an edit of <image1>).
IDENTITY (most important): {for each ref: "<imageN> is {label}" + (", keep {key_features}" if any)}.
Copy each character from their reference exactly; copy each person's face exactly: the same face shape,
eyes, eyebrows, nose, mouth and smile, cheeks, skin tone and age; the same hairstyle with the same hair
volume, curls and hairline; the same beard shape and fullness; plus the same clothes, shoes and colors.
Do not redesign, beautify or simplify the faces. Each character appears exactly once and nobody else is
in the picture.
SCENE: {shot.keyframe_prompt from the production plan, with shot_type framing; characters large in frame}
STYLE: exactly the same 2D cartoon storybook art style, line quality and shading as the reference
sheets; premium picture-book rendering with soft painterly shading, a gentle visible brush texture,
warm golden rim light along the characters' edges, and warm saturated colors.
Full-bleed 16:9 frame filling the whole canvas edge to edge: no border, no white margin, no vignette.
No written words, letters, numbers or signs anywhere in the picture.
```

Where the variable parts come from (no extra AI step):
- refs and labels: `by_likeness(shot.characters, sheets)` + the sheet labels; key accessories from
  `character_profiles.key_features` (e.g. a horse's bridle and saddle).
- the favourite toy: the parent's `personalization.toy_image_url` as its own `<imageN>` and the toy
  name from `favorites.toy.name` ("<imageN> shows only the child's {toy name}").
- previous shot (continuity): add it as the last `<imageN>` with "keep the same place and lighting".

## Lessons from the bake-off
- Do NOT pass the style reference (`storybook_soft.png`) to keyframes: its characters leaked into the
  scene (Qwen 2511 drew the style image's girl and bearded man). The sheets already carry the style.
- Generic face words ("big expressive eyes, small simplified noses") pulled every face toward a stock
  cartoon face; removing them and leading with IDENTITY made faces match the sheets.
- Name accessories that must persist (bridle, saddle, cap) or the model drops them.
- Qwen's prompt enhancer returned an empty prompt within its 4096-token budget: off.
- Qwen-Image-Edit 2511 (Apache-2.0) was weaker: smaller characters, flatter faces. Qwen Image 2.1's
  own licence is research-only; Comfy Cloud states its models are cleared for commercial use -
  get that confirmed in writing before production.
