/**
 * Register bit maps, parsed out of the generated CMSIS-SVD.
 *
 * The SVD is the right source and the IR events are not: `ir_extracted`
 * records a field COUNT (`fields: 21`), not the field list, so it cannot say
 * which bits a field covers. The SVD is also the better provenance — it is
 * emitted only from registers that passed the Z3 gate, so a strip drawn from
 * it shows verified output rather than what the model claimed.
 *
 * Pure and string-only: the player parses this in the browser, so nothing
 * here may touch node:fs.
 */

export interface BitField {
  name: string;
  msb: number;
  lsb: number;
  width: number;
  access?: string;
}

/** One register, with its gaps made explicit. */
export interface BitMap {
  register: string;
  offset: number;
  width: number;
  resetValue: number;
  fields: BitField[];
  /** Bits no field declares.
   *
   *  These are RESERVED, not a proof failure, and the distinction nearly
   *  shipped backwards. svd_emitter.py omits reserved fields on purpose —
   *  "SVD treats undeclared bits as reserved, and svd2rust warns on explicit
   *  reserved fields" — so every valid register here has holes: CR1 has 3,
   *  CR2 has 5, BRR has 16, and all three passed Z3. Drawing them as an
   *  alarm would have reported "29 of 32 bits accounted for" over output
   *  that passed every gate, which is the false positive this project calls
   *  worse than a miss.
   *
   *  Width conservation is checked on the IR, where reserved fields are
   *  declared and counted. It cannot be re-derived from the SVD, and this
   *  figure does not pretend to. */
  undeclared: number[];
  /** Bits claimed by more than one field.
   *
   *  This one IS invalid in an SVD no matter the convention: no bit belongs
   *  to two fields, so unlike a hole it is worth alarming on. */
  overlapping: number[];
}

const RANGE = /\[(\d+):(\d+)\]/;

/**
 * Parse every register in an SVD document.
 *
 * Hand-rolled rather than DOMParser so this runs identically during a server
 * render and in the browser. The input is our own generator's output, not
 * arbitrary XML, so the shape is known.
 */
export function parseSvd(xml: string): BitMap[] {
  const out: BitMap[] = [];
  // Non-greedy per <register>, so nested <fields> cannot swallow a sibling.
  for (const m of xml.matchAll(/<register>([\s\S]*?)<\/register>/g)) {
    const body = m[1];
    const register = tag(body, "name");
    if (!register) continue;

    const width = int(tag(body, "size"), 32);
    const fields: BitField[] = [];
    for (const f of body.matchAll(/<field>([\s\S]*?)<\/field>/g)) {
      const fb = f[1];
      const name = tag(fb, "name");
      const range = RANGE.exec(tag(fb, "bitRange") ?? "");
      if (!name || !range) continue;
      const msb = Number(range[1]);
      const lsb = Number(range[2]);
      if (!Number.isInteger(msb) || !Number.isInteger(lsb) || lsb > msb) continue;
      fields.push({
        name,
        msb,
        lsb,
        width: msb - lsb + 1,
        access: tag(fb, "access") ?? undefined,
      });
    }
    fields.sort((a, b) => b.msb - a.msb);

    // Counted per bit rather than summed, because a sum cannot tell a hole
    // from an overlap: drop one bit and double-claim another and the widths
    // still add to 32.
    const claims = new Array<number>(width).fill(0);
    for (const f of fields) {
      for (let b = f.lsb; b <= f.msb && b < width; b++) claims[b] += 1;
    }

    out.push({
      register,
      offset: int(tag(body, "addressOffset"), 0),
      width,
      resetValue: int(tag(body, "resetValue"), 0),
      fields,
      undeclared: claims.flatMap((c, b) => (c === 0 ? [b] : [])),
      overlapping: claims.flatMap((c, b) => (c > 1 ? [b] : [])),
    });
  }
  return out;
}

/** Pick the SVD out of a run's artifacts, whatever the chip called it. */
export function findSvd(artifacts: Record<string, string>): string | null {
  const name = Object.keys(artifacts).find((n) => n.endsWith(".svd"));
  return name ? artifacts[name] : null;
}

/** True when a field name is one the emitter generated for unused bits. */
export function isReserved(name: string): boolean {
  return /^(reserved|res|rsvd)/i.test(name);
}

function tag(xml: string, name: string): string | null {
  // The first occurrence only: inside a <field> body that is the field's own
  // name, and inside a <register> body it is the register's.
  const m = new RegExp(`<${name}>([\\s\\S]*?)</${name}>`).exec(xml);
  return m ? m[1].trim() : null;
}

function int(raw: string | null, fallback: number): number {
  if (!raw) return fallback;
  const n = raw.startsWith("0x") || raw.startsWith("0X")
    ? Number.parseInt(raw.slice(2), 16)
    : Number.parseInt(raw, 10);
  return Number.isFinite(n) ? n : fallback;
}

/** One contiguous run of bits in a register, msb-first and covering all of
 *  it. The renderer lays these out in order and needs no absolute
 *  positioning, so the strip can be plain flexbox rather than a scaled SVG
 *  whose text stretches with the container. */
export interface BitSlot {
  kind: "field" | "reserved" | "overlap";
  name: string | null;
  msb: number;
  lsb: number;
  width: number;
}

/**
 * Every bit of a register as an ordered msb-to-lsb list of runs.
 *
 * Declared fields keep their own boundaries; everything else collapses into
 * the longest possible reserved run, so sixteen unused bits draw as one block
 * rather than sixteen.
 */
export function slotsOf(map: BitMap): BitSlot[] {
  const owner = new Array<BitField | null>(map.width).fill(null);
  const dup = new Set(map.overlapping);
  for (const f of map.fields) {
    for (let b = f.lsb; b <= f.msb && b < map.width; b++) owner[b] = f;
  }

  const out: BitSlot[] = [];
  for (let b = map.width - 1; b >= 0; b--) {
    const f = owner[b];
    const kind: BitSlot["kind"] = dup.has(b) ? "overlap" : f ? "field" : "reserved";
    const name = f ? f.name : null;
    const tail = out[out.length - 1];
    // Merge only runs that are the same thing. Two adjacent 1-bit fields are
    // two slots; two adjacent reserved bits are one.
    if (tail && tail.kind === kind && tail.name === name && tail.lsb === b + 1) {
      tail.lsb = b;
      tail.width += 1;
    } else {
      out.push({ kind, name, msb: b, lsb: b, width: 1 });
    }
  }
  return out;
}
