"""Tests for SAM 3.1 table segmentation.

The response format asserted here is OBSERVED, captured from a real page
in docs/api-smoke/sam_real.json. sam-3.1 does not populate the
`annotations` array its envelope suggests; it returns inline tokens in
output_text:

    <|box;x1=116;y1=337;x2=1122;y2=430;w=1240;h=1755|>
    <|mask;x=0;y=0;data=94,1007,~!!$0l#...|>

The coordinate conversion is the part worth testing hardest. Boxes arrive
in rendered-pixel space and everything downstream works in PDF points, so
a wrong scale puts a silent factor of two into every bounding box -- and
the 600 DPI retry re-crop then reads the wrong part of the document,
quietly, while still producing plausible output.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from silicontruth.ingest.pdf_render import (
    RenderedPage,
    crop_png,
    render_page,
    scale_for,
)
from silicontruth.ingest.sam_segmenter import (
    SegmentationError,
    merge_adjacent,
    pad,
    parse_regions,
    segment_page,
)

REAL = Path("docs/api-smoke/sam_real.json")

# Two banks of one 32-bit register's grid, exactly as the model returned them.
TWO_BANKS = (
    "<0f>0,1\n"
    "<|box;x1=116;y1=337;x2=1122;y2=430;w=1240;h=1755|>"
    "<|mask;x=0;y=0;data=AAAA|>"
    "<|box;x1=116;y1=244;x2=1122;y2=335;w=1240;h=1755|>"
    "<|mask;x=0;y=0;data=BBBB|>"
)

DPI = 150  # the resolution the captured boxes were measured at


# --- parsing --------------------------------------------------------------


def test_parses_the_observed_token_format():
    regions = parse_regions(TWO_BANKS, dpi=DPI)
    assert len(regions) == 2
    assert regions[0].px == (116, 337, 1122, 430)
    assert regions[0].image_size == (1240, 1755)


def test_mask_payload_is_carried_but_never_parsed():
    """The encoding has no published specification. Decoding a guessed
    format inside the component whose job is to be trustworthy would be
    exactly the wrong trade, so it is passed through opaque for the UI."""
    regions = parse_regions(TWO_BANKS, dpi=DPI)
    assert regions[0].mask_data == "AAAA"
    assert regions[0].mask_id == "m0"


def test_boxes_stay_in_pixel_space():
    """The project's convention, documented on Provenance: a bbox is "in
    RENDER_DPI pixel space, not PDF points". crop_png takes pixels and the
    retry loop's scale_bbox moves them between resolutions."""
    r = parse_regions(TWO_BANKS, dpi=DPI)[0]
    assert r.bbox == (116.0, 337.0, 1122.0, 430.0)
    assert r.px == (116, 337, 1122, 430)


def test_points_are_available_when_dpi_independence_is_wanted():
    """At 150 DPI the fixture's grid runs from MARGIN (56 pt) to page width
    minus MARGIN (539 pt), so a correct conversion lands on those numbers."""
    r = parse_regions(TWO_BANKS, dpi=DPI)[0]
    x0, _, x1, _ = r.points()
    assert round(x0) == 56
    assert round(x1) == 539


def test_the_same_box_at_a_higher_dpi_is_fewer_points():
    a = parse_regions(TWO_BANKS, dpi=150)[0].points()
    b = parse_regions(TWO_BANKS, dpi=300)[0].points()
    assert b[2] == pytest.approx(a[2] / 2, rel=1e-6)


def test_a_nonpositive_dpi_is_refused():
    """Rather than silently producing infinite or mirrored boxes."""
    with pytest.raises(SegmentationError):
        parse_regions(TWO_BANKS, dpi=0)


def test_text_with_no_boxes_yields_nothing():
    assert parse_regions("<0f>no detections\n", dpi=DPI) == []


def test_inverted_corners_are_normalised():
    """A rectangle carries no claim about what was READ -- only where to
    look -- so normalising it is safe, unlike a bitfield's msb/lsb."""
    text = "<|box;x1=400;y1=300;x2=100;y2=100;w=1240;h=1755|>"
    r = parse_regions(text, dpi=DPI)[0]
    assert r.px == (100, 100, 400, 300)


def test_degenerate_boxes_are_dropped():
    text = "<|box;x1=100;y1=100;x2=100;y2=400;w=1240;h=1755|>"
    assert parse_regions(text, dpi=DPI) == []


def test_a_box_without_a_mask_still_parses():
    text = "<|box;x1=10;y1=10;x2=100;y2=100;w=1240;h=1755|>"
    r = parse_regions(text, dpi=DPI)[0]
    assert r.mask_id is None and r.mask_data is None


# --- merging --------------------------------------------------------------


def test_the_two_banks_of_one_register_merge():
    """A 32-bit grid is drawn as bits 31..16 above 15..0 and SAM returns
    them separately -- observed. Cropping them apart hands the extractor
    half a register and invites exactly the partial read the gates then
    have to catch."""
    merged = merge_adjacent(parse_regions(TWO_BANKS, dpi=DPI))
    assert len(merged) == 1
    assert merged[0].px == (116, 244, 1122, 430)


def test_distant_bands_do_not_merge():
    text = (
        "<|box;x1=116;y1=100;x2=1122;y2=200;w=1240;h=1755|>"
        "<|box;x1=116;y1=900;x2=1122;y2=1000;w=1240;h=1755|>"
    )
    assert len(merge_adjacent(parse_regions(text, dpi=DPI))) == 2


def test_side_by_side_bands_do_not_merge():
    """Two tables in two columns are two tables."""
    text = (
        "<|box;x1=100;y1=200;x2=500;y2=300;w=1240;h=1755|>"
        "<|box;x1=700;y1=200;x2=1100;y2=300;w=1240;h=1755|>"
    )
    assert len(merge_adjacent(parse_regions(text, dpi=DPI))) == 2


def test_merging_renumbers_the_regions():
    text = (
        "<|box;x1=116;y1=100;x2=1122;y2=200;w=1240;h=1755|>"
        "<|box;x1=116;y1=900;x2=1122;y2=1000;w=1240;h=1755|>"
    )
    merged = merge_adjacent(parse_regions(text, dpi=DPI))
    assert [r.index for r in merged] == [0, 1]


def test_merging_an_empty_list_is_empty():
    assert merge_adjacent([]) == []


# --- padding --------------------------------------------------------------


def test_padding_is_specified_in_points_and_applied_in_pixels():
    """SAM's boxes hug the ink. Losing the leftmost column means losing bit
    31, which the extractor then reports as a register that does not add up.

    The margin is given in points so it means the same thing at every
    resolution, and converted against the region's own dpi."""
    r = parse_regions(TWO_BANKS, dpi=DPI)[0]
    p = pad(r, points=6.0, top_points=0.0)
    expected_px = 6.0 * scale_for(DPI)
    assert p.bbox[0] == pytest.approx(r.bbox[0] - expected_px, abs=0.01)
    assert p.bbox[2] == pytest.approx(r.bbox[2] + expected_px, abs=0.01)


def test_padding_never_goes_negative():
    text = "<|box;x1=2;y1=2;x2=200;y2=200;w=1240;h=1755|>"
    p = pad(parse_regions(text, dpi=DPI)[0], points=20.0)
    assert p.bbox[0] >= 0 and p.bbox[1] >= 0


def test_padding_grows_the_top_far_more_than_the_bottom():
    """The asymmetry is the point: the header sits above the grid, so only
    the top needs an inch."""
    r = parse_regions(TWO_BANKS, dpi=DPI)[0]
    p = pad(r)
    above = r.bbox[1] - p.bbox[1]
    below = p.bbox[3] - r.bbox[3]
    assert above > below * 5


# --- the live response shape ---------------------------------------------


@pytest.mark.skipif(not REAL.exists(), reason="no captured SAM response")
def test_the_captured_real_response_still_parses():
    """Guards against a format change going unnoticed."""
    body = json.loads(REAL.read_text(encoding="utf-8"))
    text = "".join(
        c.get("text") or ""
        for item in body.get("output", [])
        for c in item.get("content", [])
    )
    regions = parse_regions(text, dpi=DPI)
    assert regions, "the captured response no longer yields any box"
    assert all(r.area_px > 0 for r in regions)


# --- transport ------------------------------------------------------------


def _page() -> RenderedPage:
    pdf = Path("benchmarks/suite/uart32/datasheet.pdf")
    if not pdf.exists():
        pytest.skip("run scripts/make_benchmark_suite.py first")
    return render_page(str(pdf), 1, dpi=150)


def test_scale_is_taken_from_the_page_not_an_argument():
    """REGRESSION. The first version read a `page_width_pt` attribute that
    RenderedPage does not have, so the guard always failed and it silently
    fell back to a GUESSED dpi. The page records what it was actually
    rendered at; that is the only trustworthy source."""
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["sent"] = True
        return httpx.Response(200, json={
            "output": [{"type": "message", "content": [
                {"type": "output_text", "text": TWO_BANKS}
            ]}]
        })

    page = _page()
    client = httpx.Client(
        base_url="https://example.invalid/v1",
        transport=httpx.MockTransport(handler),
    )
    regions = segment_page(page, api_key="k", client=client, merge=False)
    assert captured["sent"]
    # The dpi must be the page's own, so the box can later be converted or
    # rescaled correctly. 150 DPI -> 56 pt, the fixture's margin.
    assert regions[0].dpi == page.dpi == 150
    assert round(regions[0].points()[0]) == 56


def test_a_missing_key_is_refused_before_any_request():
    with pytest.raises(SegmentationError):
        segment_page(_page(), api_key="")


def test_an_http_error_becomes_a_segmentation_error():
    client = httpx.Client(
        base_url="https://example.invalid/v1",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(503, text="upstream down")
        ),
    )
    with pytest.raises(SegmentationError) as e:
        segment_page(_page(), api_key="k", client=client)
    assert "503" in str(e.value)


def test_an_empty_detection_is_not_an_error():
    """A page with no table is a normal outcome, not a failure. Full-page
    extraction still works without any region."""
    client = httpx.Client(
        base_url="https://example.invalid/v1",
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={
                "output": [{"type": "message", "content": [
                    {"type": "output_text", "text": "<0f>none\n"}
                ]}]
            })
        ),
    )
    assert segment_page(_page(), api_key="k", client=client) == []


def test_padding_leaves_room_above_for_the_register_header():
    """MEASURED. SAM returns the bit grid alone, but "Address offset: 0x00"
    and "Reset value: ..." are printed ABOVE it. A tight crop threw away
    exactly the values the register cannot be built without, and the
    extractor refused the read with "offset_hex: not a hex literal: ''" --
    correct behaviour on a crop that genuinely lacked the offset."""
    r = parse_regions(TWO_BANKS, dpi=DPI)[0]
    p = pad(r)
    above_pt = (r.bbox[1] - p.bbox[1]) / scale_for(DPI)
    assert above_pt >= 72, "less than an inch of headroom"


def test_headroom_is_tunable():
    r = parse_regions(TWO_BANKS, dpi=DPI)[0]
    p = pad(r, points=2.0, top_points=10.0)
    k = scale_for(DPI)
    assert p.bbox[1] == pytest.approx(r.bbox[1] - 10.0 * k, abs=0.01)
    assert p.bbox[2] == pytest.approx(r.bbox[2] + 2.0 * k, abs=0.01)


def test_a_padded_region_can_actually_be_cropped():
    """THE REGRESSION THAT MATTERS. crop_png takes pixels; the segmenter
    briefly returned points, so the crop landed on a sliver at the
    top-left and the extractor refused a read that contained no offset.
    This asserts the two agree by actually performing the crop."""
    page = _page()
    r = pad(parse_regions(TWO_BANKS, dpi=page.dpi)[0])
    png = crop_png(page, r.bbox)
    assert len(png) > 1000, "crop produced almost nothing"

    from PIL import Image
    import io

    img = Image.open(io.BytesIO(png))
    # The grid spans most of the page width; a points-vs-pixels mix-up
    # yields something a few dozen pixels wide.
    assert img.width > page.width * 0.5
    assert img.height > 200


def test_the_crop_contains_the_register_header_text():
    """Not just 'big enough' -- the crop must actually contain the offset
    and reset values, since those are what the tight crop lost."""
    from silicontruth.ingest.pdf_render import (
        extract_spans,
        spans_in_bbox,
        to_reading_order,
    )

    pdf = Path("benchmarks/suite/uart32/datasheet.pdf")
    if not pdf.exists():
        pytest.skip("run scripts/make_benchmark_suite.py first")

    page = render_page(str(pdf), 1, dpi=150)
    r = pad(parse_regions(TWO_BANKS, dpi=page.dpi)[0])
    # extract_spans scales into the dpi it is given, so ask for the same one.
    spans = extract_spans(str(pdf), 1, dpi=page.dpi)
    text = to_reading_order(spans_in_bbox(spans, r.bbox)).replace(" ", "")
    assert "Addressoffset" in text
    assert "Resetvalue" in text
