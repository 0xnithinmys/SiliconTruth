/**
 * Recorded page images and their region boxes.
 *
 * Mirrors scripts/record_pages.py. Boxes are in the PIXEL space of the
 * recorded image at the dpi named in the index -- the same convention the
 * Python side uses throughout (Provenance documents "RENDER_DPI pixel
 * space, not PDF points"). The UI therefore scales boxes by
 * renderedWidth / image.width and nothing else; converting to points on
 * the way through is how a highlight ends up a factor of two from the
 * thing it is meant to point at.
 */
import { readFile } from "node:fs/promises";
import path from "node:path";

const FIXTURES = path.join(process.cwd(), "public", "fixtures");

export interface PageRegion {
  register: string;
  bbox: [number, number, number, number];
  mask_id: string | null;
  verified: boolean;
  fields: number;
  /** True when the "region" is the whole page -- a whole-page read, not a
   *  localised one. Drawing a border around everything would imply the
   *  pipeline localised something it did not. */
  whole_page?: boolean;
  coverage?: number;
}

export interface RecordedPage {
  page: number;
  image: string;
  width: number;
  height: number;
  regions: PageRegion[];
}

export interface PageIndex {
  schema: number;
  chip: string;
  dpi: number;
  pages: RecordedPage[];
}

export async function loadPages(chip: string): Promise<PageIndex | null> {
  try {
    const raw = await readFile(path.join(FIXTURES, chip, "pages.json"), "utf8");
    const parsed = JSON.parse(raw) as PageIndex;
    // A malformed or empty index must render the honest empty state rather
    // than a page frame with nothing in it.
    if (!parsed?.pages?.length) return null;
    return parsed;
  } catch {
    return null;
  }
}
