# Face step: a parent's real face inside the scene picture

Spec for a new Comfy Cloud workflow, to build and test with Claude Cowork (2026-10-28).
Test inputs: `D:\DevData\scratch\gheras-comfy\face_step_inputs\`.

## Why

A grown-up drawn from a parent's photo looks like himself on his sheet (front view),
but in the scenes he becomes a stock face (slim, sharp jaw, full hairline with a fade,
neat black beard) whenever his head is turned or bowed. Tried and ruled out (pictures in
`D:\DevData\scratch\gheras-comfy\five\`):

| Try | Result |
|---|---|
| Face square from GPT drawings of his 3/4 and side photos | stock face |
| His sheet alone | stock face |
| 3/4 and side heads drawn by Qwen from the sheet | the heads themselves drift to the stock face |
| A rule asking for the head up, at most a slight 3/4 | Qwen ignores it when the scene has him looking at the child |
| Our keyframe workflow on a crop of the head | draws a new portrait (empty latent, denoise 1), can't edit in place |

The fix has to edit **only the face region of the finished scene picture**, keep its
angle, gaze, expression, light and painted style, and take the identity from his photo
and sheet.

## What Comfy Cloud has (checked through `/api/object_info`, 2026-10-28)

- Edit models: `qwen_image_edit_2511_*` and `qwen_image_edit_2509_*` (UNETLoader),
  `TextEncodeQwenImageEditPlus` (up to 3 reference images), `flux1-dev-kontext*`,
  `flux.1-fill-dev*`.
- Inpainting by crop and stitch: `FL_InpaintCrop`, `FL_Inpaint_Stitch`; also the
  `INPAINT_*` nodes and `SetLatentNoiseMask`.
- Face tools: `FaceDetailer` (Impact), `IPAdapterUnifiedLoaderFaceID` (FACEID PLUS V2,
  PORTRAIT), `IPAdapterInsightFaceLoader`, face parsing nodes.
- No PuLID, InstantID or InfiniteYou.

## Candidate A (try first): crop, Qwen Image Edit 2511, stitch

1. `LoadImage {{scene_image}}` (1536x864) and `LoadImageMask {{face_mask}}` (same size,
   white oval over the grown-up's head; we draw it from a Florence head box).
2. `FL_InpaintCrop`: context around the mask (~2x), the crop resized to ~1024.
3. Qwen Image Edit 2511 on the crop: the crop is the image being edited (its own latent,
   not an empty one); `{{ref_1}}` = the head from his sheet, `{{ref_2}}` = his photo at
   the closest angle. Denoise to tune (start 0.6-0.8) so the angle and expression stay.
   The noise is limited to the mask (`SetLatentNoiseMask` or the inpaint conditioning).
4. `FL_Inpaint_Stitch` back into the full scene, feathered edge.
5. `SaveImageAdvanced` with prefix `{{output_prefix}}`: the full scene, same size.

## Candidate B (if A loses the likeness): FaceDetailer + IPAdapter FaceID

`FaceDetailer` on the scene with an illustration SDXL checkpoint (e.g.
`Illustrious-XL-sdxl`), identity from `IPAdapterUnifiedLoaderFaceID` (FACEID PLUS V2 or
PORTRAIT) fed with his photo, the painted style kept through a low denoise and the
scene's own colors. Same inputs and output as A.

## Contract with the app (`services/ai/comfy.py`)

- API-format JSON saved as `backend/comfy_workflows/face_fix_api.json`.
- Placeholders as strings in node inputs: `{{scene_image}}`, `{{face_mask}}`, `{{ref_1}}`,
  `{{ref_2}}`, `{{scene_prompt}}`, `{{seed}}` (int), `{{output_prefix}}`. Images are
  uploaded by the app and the placeholder becomes the uploaded name. Denoise and other
  floats fixed in the JSON (tell us the value), or a `{{denoise}}` placeholder if it needs
  tuning per shot.
- Say the output node id and which node holds each placeholder.

The prompt we will send (only the identity part changes per person):

> Edit only the grown man's head inside the mask so it is exactly the man of image 2 and
> image 3: the same face shape and width, cheeks, forehead and hairline (bare temples
> where he has them), the same amount and texture of hair on top, eyebrows, eyes, nose,
> mouth, ears, and the same beard shape, length and color (grey hairs where he has them).
> Keep the head's angle, size and place, the gaze, the expression, the light and the
> painted storybook style of the picture. Nothing outside the head changes.

## Acceptance (on `scene_kitchen.png` and `scene_swing.png`)

Head boxes are in `father_head_boxes.json` (x, y, w, h in the 1536x864 scene).

1. He looks like his photos: broad face and full cheeks, bare receding temples, short
   sparse curly hair on top, grey hairs in the beard on the chin.
2. Same angle, gaze direction and expression as before; same light.
3. Painted storybook look like the rest of the picture, not a photo pasted in; no seam
   or halo.
4. Nothing outside the head changes (the child, hands, background).
5. Under ~25 GPU-seconds per call (about 5 US cents).

Deliver: the JSON, the before/after crops of both scenes, the GPU seconds per call.

## How the app will use it

For each shot picture (the start picture and, with the pinned last frame, the end
picture) that shows a grown-up drawn from a photo: Florence finds his head, the app draws
the oval mask, this workflow fixes the face, and the review then checks the fixed
picture. One cost line per order. A failed call keeps the picture as drawn.
