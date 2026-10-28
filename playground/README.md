# SAM 3.1 and Muse playground

A learning area for small, repeatable experiments before production implementation. The camera playground is runnable; no model API calls are implemented. See [camera setup](camera/README.md) and [camera source roadmap](../docs/CAMERA_SOURCES.md).

## Learning sequence

1. **First SAM image:** send an authorized test image and a simple concept prompt such as person. Inspect the returned boxes/masks and coordinate system.
2. **Prompt limitations:** compare concrete concepts, clutter, lighting, and partial occlusion using the same inputs.
3. **First video:** use a short recorded clip. Inspect frame timestamps, tracking identity, request limits, and processing time. Do not assume streaming results means live-camera latency.
4. **First Muse request:** provide a frame and monitoring intent. Inspect the proposed structured rule and ambiguous instructions.
5. **Tool workflow:** let Muse request segmentation and configuration validation; review the resulting zone/rule before activation.
6. **Performance:** repeat controlled inputs and report latency, event errors, throughput, and cost where available.

## Local data

Use `data/` for local images/videos and `outputs/` for generated responses/overlays; these directories are ignored by Git. Publish only assets you have permission to share. Keep credentials in local environment variables.

Copy [the report template](reports/TEMPLATE.md) for each experiment. Include scripts and sanitized configuration when implemented, so another developer can reproduce the result.

## Promotion rule

Only move proven behavior into the application after understanding its output, errors, and limitations. Keep experiments independent from production service imports.

