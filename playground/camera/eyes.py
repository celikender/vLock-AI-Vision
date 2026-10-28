"""Ask Claude for visible eye coordinates; the browser draws the squares."""
from io import BytesIO
import json
from PIL import Image, ImageOps, UnidentifiedImageError
from analysis import AnalysisError, analyze_photo

EYE_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "boxes": {"type": "array", "items": {
            "type": "object", "properties": {
                name: {"type": "integer"} for name in ("x1", "y1", "x2", "y2")
            }, "required": ["x1", "y1", "x2", "y2"], "additionalProperties": False,
        }},
    },
    "required": ["answer", "boxes"], "additionalProperties": False,
}


def locate_eyes(jpeg):
    try:
        with Image.open(BytesIO(jpeg)) as original:
            if original.width * original.height > 20_000_000:
                raise AnalysisError("Photo dimensions are too large. Capture a smaller image.", 400)
            image = ImageOps.exif_transpose(original).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError):
        raise AnalysisError("Cannot read this photo. Capture a new photo.", 400) from None
    # At most 36x36 patches on a 28px grid: below the standard vision budget.
    # This avoids further model downscaling, so returned pixels match this image.
    image.thumbnail((1008, 1008), Image.Resampling.LANCZOS)
    width, height = image.size
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    prompt = (
        f"Locate each clearly visible human eye in this {width} by {height} pixel photo. "
        "Return tight bounding rectangles around individual eyes (not the whole face). "
        "Use absolute pixel coordinates x1,y1 for the top-left and x2,y2 for the "
        "bottom-right, origin at the image top-left. Coordinates must stay inside "
        f"0..{width} horizontally and 0..{height} vertically. "
        "Include only eyes you can actually locate; do not invent occluded eyes. "
        "If there are no clearly visible eyes, return an empty boxes array. "
        "In answer, briefly explain what you found and mention uncertainty if needed."
    )
    result = analyze_photo(buffer.getvalue(), prompt, output_schema=EYE_SCHEMA)
    try:
        payload = json.loads(result["answer"])
        boxes = payload["boxes"]
        if not isinstance(payload["answer"], str) or not isinstance(boxes, list) or len(boxes) > 20:
            raise ValueError("Invalid result")
        for box in boxes:
            values = [box[key] for key in ("x1", "y1", "x2", "y2")]
            if any(type(value) is not int for value in values):
                raise ValueError("Invalid coordinates")
            x1, y1, x2, y2 = values
            if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
                raise ValueError("Out of bounds")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise AnalysisError("Claude returned invalid eye coordinates. Try another photo.") from None
    return {**result, "answer": payload["answer"], "boxes": boxes,
            "coordinate_width": width, "coordinate_height": height}
