# Decoder notes: <format name>

| | |
|---|---|
| Games and builds seen | title, version, platform (no game data) |
| Signature | magic bytes and where they are |
| Sources | documentation, published engine source, analysed loader functions |
| Reader | module path in `cutcontent/formats/` or private only |
| Support level | detection / inventory / preview / gameplay |

## Layout

Header fields with offsets, sizes, units and byte order. Tables, compression,
alignment, how names are stored.

## How it was verified

Counts and checksums compared, landmarks checked, rendering compared with the
running game. Tests with self-made data in `tests/`.

## Limits

What is not decoded yet and why. Encrypted parts are reported as not covered.
