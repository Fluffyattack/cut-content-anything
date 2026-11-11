# Inventory and decoding

## Inventory first

`cutcontent scan PATH` lists every file the readers can see, with container,
internal path, offset and size. `cutcontent search BUILD --term WORD --json`
searches names, metadata and decoded text, and reports its byte and item
coverage. Keep that coverage in the notes.

## Recognising a container

- Magic numbers at offset 0, or at a fixed offset in a header.
- A table of contents: count, then fixed-size records with offset and size that
  point inside the file and do not overlap.
- Name tables: null-terminated strings, or hashes that never repeat.
- Compression: high-entropy blocks, known stream headers (zlib `78 9C`, LZ
  variants with a size prefix).
- Alignment: offsets that are all multiples of 2048 (disc sectors) or of 4/16/32.

## Writing a reader

1. Read-only file access; every offset, count and size is checked against the
   real file size before use.
2. Return what was read and what could not be read. Out-of-range entries are
   reported as incomplete, as the cartridge reader already does.
3. Name fields after their meaning once established; keep unknown fields as
   `unknown_<offset>` until evidence says more.
4. Test on the real input privately, then write self-made test data for the
   public test suite.
5. Document the format with `templates/decoder.md` and add the support level to
   `docs/FORMAT_SUPPORT.md`.

## Showing maps

Maps go through the shared scene package so any decoder's output opens in the
same viewer. See [gallery-and-scenes.md](gallery-and-scenes.md).

## When the format is only defined by code

Find the loader in the executable and follow it: see
[reverse-engineering.md](reverse-engineering.md).
