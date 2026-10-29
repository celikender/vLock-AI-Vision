# Streaming checkpoint compatibility proof of concept

## Result — 2026-10-28

The existing SAM 3.1 multiplex checkpoint **does not load into the tested
Transformers Sam3VideoModel** through the official SAM3 conversion utility.
There is no streaming inference result, FPS benchmark, or tracking-continuity
claim from this experiment. The working four-frame pipeline is untouched.

The separate runtime uses Transformers **5.21.0**, reusing the existing
PyTorch **2.10.0+cu128** / torchvision **0.25.0+cu128** libraries. Transformers
and its new dependencies are installed only under ignored
`playground/outputs/streaming-env-linux/`; the working Ubuntu CUDA environment
has not been upgraded or modified. No additional checkpoint was downloaded.
Only small configuration/tokenizer assets and the official converter source
were fetched. No camera imagery was uploaded or needed for this structural test.

## Actual checks

1. The existing local `sam3.1_multiplex.pt` contains **1,623** tensor entries.
   Its detector/tracker container names differ from the converter's expected
   `sam3_model` and `sam2_predictor.model` names.
2. The official conversion was tested as supplied, then repeated after adapting
   only those container prefixes. Combined attention projections were split,
   position embeddings adjusted, point embeddings joined, and the text projection
   transposed according to the official converter. Tensor values were not
   approximated, truncated to fit a different tracker, or dropped to hide errors.
3. The converted dictionary contains **1,995** entries. The model built from the
   repository's video config expects **1,797** entries. After the container-name
   adaptation, **118 keys are missing**, **316 are unexpected**, and **26 common
   keys have incompatible shapes**.
4. `model.load_state_dict(..., strict=True, assign=True)` failed with missing-key,
   unexpected-key and size-mismatch errors. Both source and target tensors were
   on PyTorch's meta device for this audit: this validates the actual required
   names/shapes without allocating a second GPU model or creating random-weight
   inference. No converted checkpoint was saved.
5. Independently, the real processor imported, initialized
   `processor.init_video_session()` with no `video` argument on the CUDA device,
   and accepted `person` and `forklift` through `add_text_prompt`. These are
   processor/session checks, not successful segmentation or tracking inference.
   Adding a second prompt is additive. Replacing the user's target should create
   a new session while retaining the loaded model once compatible weights exist.

Examples of actual shape mismatches, after prefix normalization and conversion:

| Target tensor | Existing checkpoint | Streaming model expects |
|---|---|---|
| `tracker_model.mask_decoder.iou_token.weight` | `[16,256]` | `[1,256]` |
| `tracker_model.mask_decoder.mask_tokens.weight` | `[48,256]` | `[4,256]` |
| `tracker_model.occlusion_spatial_embedding_parameter` | `[16,256]` | `[1,64]` |
| `tracker_model.memory_temporal_positional_encoding` | `[7,1,1,256]` | `[7,1,1,64]` |
| `tracker_model.memory_encoder.mask_downsampler.layers.0.conv.weight` | `[16,32,3,3]` | `[4,1,3,3]` |

The source checkpoint uses a 16-slot multiplex tracker; the tested streaming model
uses `Sam3TrackerVideoModel` with a different mask decoder and memory encoder.
The installed tracker constructs its mask downsampler with one input channel,
whereas the trained checkpoint's first convolution expects 32. This is more than
a naming or file-format mismatch. Changing memory-width configuration alone
cannot supply the multiplex computation, trained slot embeddings, and missing
components. The tested official conversion plus harmless prefix adaptation is
not a valid lossless conversion for this checkpoint.

## Next viable options

- Use a checkpoint explicitly compatible with this Transformers video model,
  such as its documented `facebook/sam3` Transformers weights. This is an
  additional large download and a different model variant; it was not downloaded
  automatically for this test.
- To retain these exact SAM 3.1 weights, implement or obtain a compatible multiplex
  architecture and streaming state adapter. That requires model/inference code
  work and validation, beyond state-dictionary renaming. It has not been done by
  this proof of concept.

Keep the working four-frame fallback until one option passes strict loading and
actual sustained camera inference. Live IDs beyond four frames, prompt-switch
inference, FPS, GPU utilization, inference memory, and end-to-end latency are
**not measured** here because loading failed. Previously measured fallback
timings remain historical observations, not a valid streaming comparison.

After a compatible model is available, the streaming experiment should keep one
inference session, use the documented per-frame preprocessing/forward/postprocess
calls, and isolate UI prompt changes with session revisions. A latest-frame input
slot must bound camera backlog. Also inspect/prune retained frame storage safely:
this installed session's `add_new_frame` retains processed frames in a dictionary,
so a bounded input queue alone does not establish bounded long-run model memory.
Measure host receipt-to-result latency separately from camera-reported frame age;
neither proves sensor-to-display latency without a synchronized hardware test.

## Reproduce

From the project PowerShell terminal, the cached offline audit is:

```powershell
.\playground\segmentation\streaming_poc\check_checkpoint.ps1
```

Exit code **2** indicates checkpoint incompatibility. The script never loads
weights into the working predictor or changes the fallback. Full counts, every
key and shape mismatch, exact strict-load errors, config revision/hash, processor
API results and converter hash are saved in ignored
`playground/outputs/streaming_compatibility.json`.

For a fresh isolated setup, run from Ubuntu in the project directory:

```bash
~/.local/share/vlock-vision/sam-env/bin/python playground/segmentation/streaming_poc/setup_runtime.py
playground/outputs/streaming-env-linux/bin/python playground/segmentation/streaming_poc/compatibility.py
```

The source converter is pinned separately because the installed wheel omits it:
commit `144ecf007b8b4f2910da104c84a79801db6985a6`, SHA-256
`7dcf1fd3c8a1b437fbba46282b771fcb0a67bef4326cdbae96b9bc0c966cdc4a`.
The local source/provenance cache makes subsequent checks offline and detects
source changes. The utility's missing/unexpected-key warnings are not treated as
successful loading; this audit requires a strict match.

References: [streaming API](https://huggingface.co/docs/transformers/en/model_doc/sam3_video),
[official conversion source](https://github.com/huggingface/transformers/blob/144ecf007b8b4f2910da104c84a79801db6985a6/src/transformers/models/sam3_video/convert_sam3_video_to_hf.py),
[SAM 3.1 checkpoint repository](https://huggingface.co/facebook/sam3.1).
