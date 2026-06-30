#!/usr/bin/env python3
"""Verify the fixed DSEG7 font file has correct glyph_dsc layout."""
import struct, sys, re, lz4.block

def parse_c_array(content, name):
    pat = re.compile(r'(?:static\s+)?(?:const\s+)?uint8_t\s+' + re.escape(name) +
                     r'\[\]\s*[^\{]*\{\s*([^}]+)\}', re.DOTALL)
    m = pat.search(content)
    if not m: return None
    vals = []
    for v in re.finditer(r'0x[0-9a-fA-F]+|\d+', m.group(1)):
        vals.append(int(v.group(0), 0))
    return vals

def get_prop(content, name):
    m = re.search(r'\.' + re.escape(name) + r'\s*=\s*(\d+)', content)
    return int(m.group(1)) if m else 0

with open(sys.argv[1], 'r') as f:
    content = f.read()

comp_data = parse_c_array(content, 'lz4FontData')
uncomp_size = get_prop(content, 'uncomp_size')
comp_size = get_prop(content, 'comp_size')

print(f"File: {sys.argv[1]}")
print(f"uncomp_size={uncomp_size} comp_size={comp_size}")

raw = lz4.block.decompress(bytes(comp_data), uncompressed_size=uncomp_size)
print(f"Decompressed: {len(raw)} bytes")

# Read glyph_dsc entries (8 bytes each)
num_glyphs = 0
stride = 8
while num_glyphs * stride < len(raw):
    offset = num_glyphs * stride
    if offset + stride > len(raw):
        break
    entry = raw[offset:offset + stride]
    packed = struct.unpack_from('<I', entry, 0)[0]
    bitmap_index = packed & 0xFFFFF
    adv_w = (packed >> 20) & 0xFFF
    box_w = entry[4]
    box_h = entry[5]
    ofs_x = entry[6] - 256 if entry[6] > 127 else entry[6]
    ofs_y = entry[7] - 256 if entry[7] > 127 else entry[7]
    print(f"  glyph[{num_glyphs}]: bitmap_idx={bitmap_index} adv_w={adv_w} box={box_w}x{box_h} ofs=({ofs_x},{ofs_y})")
    num_glyphs += 1
    # Stop after reading reasonable number or hitting bitmap area
    if offset + stride >= 200:  # first 200 bytes should cover glyph_dsc
        break

print(f"\nTotal glyph entries found: {num_glyphs}")

# Check what comes after glyph_dsc (should be cmap lists)
after_glyph = num_glyphs * stride
print(f"\nData at offset {after_glyph} (after glyph_dsc):")
remainder = raw[after_glyph:after_glyph+50]
print(' '.join(f'{b:02x}' for b in remainder))

# Find glyph_bitmap offset
glyph_bitmap_ofs = get_prop(content, 'glyph_bitmap')
print(f"\nglyph_bitmap offset in .c file: {glyph_bitmap_ofs}")
if glyph_bitmap_ofs < len(raw):
    print(f"First 16 bytes of bitmap: {' '.join(f'{b:02x}' for b in raw[glyph_bitmap_ofs:glyph_bitmap_ofs+16])}")
