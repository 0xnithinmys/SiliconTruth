"""Stage 1b: locate tables on a page with SAM 3.1.

WHAT THIS IS FOR. Full-page extraction already works, so this is an
optimisation, not a dependency. It earns its place on dense pages: a
reference manual page carrying four register descriptions sends four times
the pixels and asks the model to keep four bit grids straight at once.
Cropping to one table at a time means fewer tokens, a larger effective
resolution per table, and -- the part that matters for verification -- a
bounding box to re-crop at 600 DPI when the Z3 retry loop needs one row
read again.

THE RESPONSE FORMAT IS OBSERVED, NOT GUESSED. sam-3.1 is served on
/v1/responses and does not populate the `annotations` array that the
shape suggests. It returns inline tokens in `output_text`:

    <0f>0,1
    <|box;x1=116;y1=337;x2=1122;y2=430;w=1240;h=1755|>
    <|mask;x=0;y=0;data=94,1007,~!!$0l#Lh&CTqbNk7y_[...|>

Captured from a real page in docs/api-smoke/sam_real.json. The box is what
this module needs; the mask payload is an opaque encoding that is carried
through untouched for the UI overlay and never parsed here. Decoding a
format we do not have a specification for, in the component whose job is
to be trustworthy, would be exactly the wrong trade.

COORDINATES. Boxes stay in the RENDERED IMAGE's pixel space, which is the
convention the rest of the project already uses and documents: Provenance
records a bbox "in RENDER_DPI pixel space, not PDF points", crop_png takes
pixels, and the retry loop's scale_bbox moves a box between resolutions.

An earlier version of this module converted to points instead, on the
reasoning that points are DPI-independent. They are, and it was still
wrong: crop_png received points, cropped a sliver at the top-left corner,
and the extractor refused the result with "offset_hex: not a hex literal:
''" -- a correct refusal of a crop that genuinely contained no offset. One
convention, consistently applied, beats a better convention applied to
half the codebase. `points()` is there for anything that needs the
DPI-independent form.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, replace

import httpx

from silicontruth.ingest.pdf_render import BBox, RenderedPage, scale_for
from silicontruth.models.provider import ProviderError

# <|box;x1=116;y1=337;x2=1122;y2=430;w=1240;h=1755|>
BOX_TOKEN = re.compile(
    r"<\|box;x1=(?P<x1>-?\d+);y1=(?P<y1>-?\d+);"
    r"x2=(?P<x2>-?\d+);y2=(?P<y2>-?\d+);"
    r"w=(?P<w>\d+);h=(?P<h>\d+)\|>"
)
# <|mask;x=0;y=0;data=...|>  -- payload deliberately opaque.
MASK_TOKEN = re.compile(r"<\|mask;x=(?P<x>-?\d+);y=(?P<y>-?\d+);data=(?P<data>[^|]*)\|>")


class SegmentationError(ProviderError):
    """SAM returned something this module cannot use."""


@dataclass(frozen=True)
class Region:
    """One detected region, in the rendered page's pixel space.

    `dpi` is carried so the box can be converted to points, or rescaled to
    another resolution, without the caller having to remember which render
    it came from. Forgetting that is how a 600 DPI re-crop reads the wrong
    half of a page while still producing plausible output.
    """

    index: int
    bbox: BBox                          # x0, y0, x1, y1 in rendered pixels
    dpi: int
    image_size: tuple[int, int]         # w, h the model measured against
    mask_id: str | None = None
    mask_data: str | None = None        # opaque; for the UI, never parsed

    @property
    def px(self) -> tuple[int, int, int, int]:
        return tuple(int(round(v)) for v in self.bbox)  # type: ignore[return-value]

    @property
    def area_px(self) -> float:
        return (self.bbox[2] - self.bbox[0]) * (self.bbox[3] - self.bbox[1])

    def points(self) -> BBox:
        """The same box in PDF points, for anything that needs DPI independence."""
        k = scale_for(self.dpi)
        return (self.bbox[0] / k, self.bbox[1] / k,
                self.bbox[2] / k, self.bbox[3] / k)


def parse_regions(
    text: str, *, dpi: int, image_size: tuple[int, int] | None = None
) -> list[Region]:
    """Pull boxes (and any masks) out of SAM's inline token stream.

    Coordinates are left in the pixel space of the render they describe.
    """
    if dpi <= 0:
        raise SegmentationError(f"dpi must be positive, got {dpi}")

    masks = list(MASK_TOKEN.finditer(text))
    regions: list[Region] = []
    for i, m in enumerate(BOX_TOKEN.finditer(text)):
        x1, y1, x2, y2 = (int(m.group(k)) for k in ("x1", "y1", "x2", "y2"))
        w, h = int(m.group("w")), int(m.group("h"))
        # The model occasionally emits a box with the corners the other way
        # round. Normalising is safe here because, unlike a bitfield's
        # msb/lsb, a rectangle carries no claim about what was read -- only
        # where to look.
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        if x2 <= x1 or y2 <= y1:
            continue  # degenerate; nothing to crop

        mask = masks[i] if i < len(masks) else None
        regions.append(
            Region(
                index=i,
                bbox=(float(x1), float(y1), float(x2), float(y2)),
                dpi=dpi,
                image_size=image_size or (w, h),
                mask_id=f"m{i}" if mask else None,
                mask_data=mask.group("data") if mask else None,
            )
        )
    return regions


def merge_adjacent(
    regions: list[Region], *, gap_px: int = 24, overlap_ratio: float = 0.6
) -> list[Region]:
    """Join vertically stacked bands that belong to one table.

    A 32-bit register's grid is drawn as two banks, bits 31..16 above
    15..0, and SAM returns them as two separate regions -- that is what it
    did on the fixture. Cropping them apart would hand the extractor half a
    register and invite exactly the kind of partial read the gates then have
    to catch. Bands are merged when they overlap horizontally and sit within
    `gap_px` of each other vertically.
    """
    if not regions:
        return []

    ordered = sorted(regions, key=lambda r: (r.bbox[1], r.bbox[0]))
    merged: list[Region] = []
    current = ordered[0]

    for nxt in ordered[1:]:
        cx1, cy1, cx2, cy2 = current.bbox
        nx1, ny1, nx2, ny2 = nxt.bbox

        overlap = min(cx2, nx2) - max(cx1, nx1)
        narrower = min(cx2 - cx1, nx2 - nx1)
        horizontally_aligned = narrower > 0 and overlap / narrower >= overlap_ratio
        vertically_close = ny1 - cy2 <= gap_px

        if horizontally_aligned and vertically_close:
            current = replace(
                current,
                bbox=(min(cx1, nx1), min(cy1, ny1), max(cx2, nx2), max(cy2, ny2)),
            )
        else:
            merged.append(current)
            current = nxt
    merged.append(current)

    return [replace(r, index=i) for i, r in enumerate(merged)]


def pad(
    region: Region, *, points: float = 6.0, top_points: float = 78.0
) -> Region:
    """Grow a box, asymmetrically, with much more room above.

    Two separate problems, one fix.

    SAM's boxes hug the ink, so a grid's outermost rule line and the digits
    pressed against it can fall a pixel outside. Losing the leftmost column
    means losing bit 31, which the extractor then reports as a register
    that does not add up.

    The larger top margin is the more important one, and it was found by
    cropping a real page: SAM returns the bit grid alone, but
    "Address offset: 0x00" and "Reset value: 0x0000 0000" are printed
    ABOVE the grid, along with the register's name. A tight crop therefore
    throws away exactly the values the register cannot be built without.
    An inch of headroom captures that block in the layout idiom these
    manuals use.

    The margins are given in POINTS so they mean the same thing at every
    resolution, and converted here against the region's own dpi.
    """
    k = scale_for(region.dpi)
    side, top = points * k, top_points * k
    x0, y0, x1, y1 = region.bbox
    return replace(
        region,
        bbox=(max(0.0, x0 - side), max(0.0, y0 - top), x1 + side, y1 + side),
    )


def segment_page(
    page: RenderedPage,
    *,
    api_key: str,
    base_url: str = "https://api.meta.ai/v1",
    model: str = "sam-3.1",
    prompt: str = "table",
    timeout: float = 180.0,
    merge: bool = True,
    client: httpx.Client | None = None,
) -> list[Region]:
    """Ask SAM where the tables are on an already-rendered page."""
    if not api_key:
        raise SegmentationError("no API key configured for segmentation")

    uri = "data:image/png;base64," + base64.b64encode(page.png).decode()
    own_client = client is None
    c = client or httpx.Client(
        base_url=base_url,
        timeout=httpx.Timeout(timeout, connect=20.0),
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"},
        follow_redirects=True,
    )
    try:
        r = c.post(
            "/responses",
            json={
                "model": model,
                "input": [{
                    "role": "user",
                    "content": [
                        {"type": "input_image", "image_url": uri},
                        {"type": "input_text", "text": prompt},
                    ],
                }],
            },
        )
    except Exception as e:
        raise SegmentationError(f"{type(e).__name__}: {e}") from e
    finally:
        if own_client:
            pass  # closed below, after the body is read

    try:
        if r.status_code != 200:
            raise SegmentationError(f"HTTP {r.status_code}: {r.text[:300]}")
        body = r.json()
        text = "".join(
            c_.get("text") or ""
            for item in body.get("output", [])
            for c_ in item.get("content", [])
        )
    finally:
        if own_client:
            c.close()

    # The scale comes from the page's OWN dpi, not from the argument. The
    # page records what it was actually rendered at; the argument records
    # what a caller believed. When those differ -- a pre-rendered page
    # passed straight through, say -- trusting the argument puts a silent
    # factor of two into every bounding box, and a 600 DPI re-crop then
    # reads the wrong part of the document.
    # The dpi comes from the page's OWN record of what it was rendered at,
    # never from a caller's belief about it.
    regions = parse_regions(
        text, dpi=page.dpi, image_size=(page.width, page.height)
    )
    return merge_adjacent(regions) if merge else regions
