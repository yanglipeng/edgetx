#!/usr/bin/env python3
"""
Repair DSEG7 font .c files: glyph_dsc entries are packed as 16 bytes each,
but LV_FONT_FMT_TXT_LARGE=0 means they should be 8 bytes each (bitfield).

Usage: python3 fix_dseg7_glyph.py <path_to_c_file>
"""
import struct
import sys
import os
import re
import lz4.block


def parse_c_array(content, name):
    """Extract uint8_t array values by variable name."""
    pat = re.compile(
        r'(?:static\s+)?(?:const\s+)?uint8_t\s+' +
        re.escape(name) + r'\[\]\s*[^\{]*\{\s*([^}]+)\}',
        re.DOTALL)
    m = pat.search(content)
    if not m: return None
    vals = []
    for v in re.finditer(r'0x[0-9a-fA-F]+|\d+', m.group(1)):
        vals.append(int(v.group(0), 0))
    return vals


def get_font_prop(content, name):
    m = re.search(r'\.' + re.escape(name) + r'\s*=\s*(\d+)', content)
    return int(m.group(1)) if m else 0


def get_cmap_glyph_count(content):
    """Parse cmaps and calculate total number of glyph_dsc entries needed."""
    max_glyph_id = 0
    entries = re.finditer(
        r'\{\s*\.range_start\s*=\s*(\d+)\s*,?\s*'
        r'\.\s*range_length\s*=\s*(\d+)\s*,?\s*'
        r'\.\s*glyph_id_start\s*=\s*(\d+)\s*,?\s*'
        r'\.\s*list_length\s*=\s*(\d+)\s*,?\s*'
        r'\.\s*type\s*=\s*(\d+).*?\}',
        content, re.DOTALL)
    for m in entries:
        glyph_start = int(m.group(3))
        range_len = int(m.group(2))
        list_len = int(m.group(4))
        cmap_type = int(m.group(5))
        if cmap_type == 0 or cmap_type == 1:
            # Format 0: glyph_id = glyph_id_start + rcp
            last_id = glyph_start + range_len - 1
        else:
            # Sparse: glyph_id = glyph_id_start + search(list)
            last_id = glyph_start + list_len - 1
        if last_id > max_glyph_id:
            max_glyph_id = last_id
    # glyph_dsc includes index 0 (null glyph)
    return max_glyph_id + 1


def repair_font_c(c_file_path):
    with open(c_file_path, 'r') as f:
        content = f.read()

    # Parse compressed data
    comp_data = parse_c_array(content, 'lz4FontData')
    if not comp_data:
        print(f"  ERROR: Could not parse lz4FontData")
        return False

    # Get metadata
    uncomp_size = get_font_prop(content, 'uncomp_size')
    comp_size = get_font_prop(content, 'comp_size')
    old_bitmap_ofs = get_font_prop(content, 'glyph_bitmap')

    if not uncomp_size or not comp_size:
        print(f"  ERROR: missing size info")
        return False

    print(f"  uncomp_size={uncomp_size}, comp_size={comp_size}, bitmap_ofs={old_bitmap_ofs}")

    # Count glyph_dsc entries
    num_glyphs = get_cmap_glyph_count(content)
    print(f"  glyph entries={num_glyphs}")

    old_glyph_dsc_size = num_glyphs * 16
    new_glyph_dsc_size = num_glyphs * 8
    delta = old_glyph_dsc_size - new_glyph_dsc_size  # bytes to remove

    # Decompress
    try:
        raw = lz4.block.decompress(bytes(comp_data), uncompressed_size=uncomp_size)
    except Exception as e:
        print(f"  Decompress failed: {e}")
        return False

    if len(raw) != uncomp_size:
        print(f"  Decompressed size mismatch: {len(raw)} vs {uncomp_size}")
        return False

    # Verify old glyph_dsc boundaries
    cmap_lists_size = old_bitmap_ofs - old_glyph_dsc_size
    print(f"  old_glyph_dsc_size={old_glyph_dsc_size}, cmap_lists_size={cmap_lists_size}")

    # Extract and repack glyph_dsc entries (16 bytes → 8 bytes each)
    new_data = bytearray()

    for i in range(num_glyphs):
        offset = i * 16
        entry = raw[offset:offset + 16]
        # Read assuming old format: <IIHHhh
        bitmap_index, adv_w, box_w, box_h, ofs_x, ofs_y = struct.unpack_from('<IIHHhh', entry, 0)
        # Repack in new format: bitmap_index:20 + adv_w:12 in uint32_t, then 4 bytes
        packed = (bitmap_index & 0xFFFFF) | ((adv_w & 0xFFF) << 20)
        new_data += struct.pack('<I', packed)
        new_data += struct.pack('<BBbb', box_w, box_h, ofs_x, ofs_y)

    # Copy cmap lists
    cmap_lists_start = old_glyph_dsc_size
    cmap_lists_end = cmap_lists_start + cmap_lists_size
    new_data += raw[cmap_lists_start:cmap_lists_end]

    # Copy glyph_bitmap (adjusted offset)
    new_bitmap_ofs = len(new_data)
    new_data += raw[old_bitmap_ofs:]

    # Update cmap unicode_list offsets
    # The offsets are relative within the compressed data
    # They need to be reduced by delta if they point past glyph_dsc
    def fix_offset(m):
        full = m.group(0)
        val = int(m.group(1))
        if val > old_glyph_dsc_size:
            new_val = val - delta
            return full.replace(m.group(1), str(new_val))
        return full

    # Fix unicode_list and glyph_id_ofs_list offsets in cmaps
    content = re.sub(
        r'(\.unicode_list\s*=\s*)(\d+)',
        lambda m: m.group(1) + str(int(m.group(2)) - delta if int(m.group(2)) > 0 else 0),
        content)
    content = re.sub(
        r'(\.glyph_id_ofs_list\s*=\s*)(\d+)',
        lambda m: m.group(1) + str(int(m.group(2)) - delta if int(m.group(2)) > 0 else 0),
        content)

    # Update metadata
    new_uncomp_size = len(new_data)
    content = re.sub(r'(\.uncomp_size\s*=\s*)\d+', r'\g<1>' + str(new_uncomp_size), content)
    content = re.sub(r'(\.glyph_bitmap\s*=\s*)\d+', r'\g<1>' + str(new_bitmap_ofs), content)

    # Recompress
    try:
        new_comp = lz4.block.compress(bytes(new_data), mode='high_compression', store_size=False)
    except Exception as e:
        print(f"  Recompress failed: {e}")
        return False

    new_comp_size = len(new_comp)
    content = re.sub(r'(\.comp_size\s*=\s*)\d+', r'\g<1>' + str(new_comp_size), content)

    # Update compressed data array
    # Replace everything between '{' and '}' after 'lz4FontData[]'
    array_start = content.find('lz4FontData[] __FLASH = {')
    if array_start < 0:
        print(f"  ERROR: could not find lz4FontData array")
        return False
    brace_start = content.index('{', array_start)
    brace_end = content.index('};', brace_start)

    new_array = ''
    for i, b in enumerate(new_comp):
        new_array += f'0x{b:02x},'
        if (i & 0x0F) == 0x0F:
            new_array += '\n'
    if (len(new_comp) & 0x0F) != 0:
        new_array += '\n'

    content = content[:brace_start + 1] + '\n' + new_array + content[brace_end:]

    # Update lvglFontBufSize (uncomp_size + overhead which stays same, just adjust uncomp_size part)
    old_buf_size = get_font_prop(content, 'lvglFontBufSize')
    buf_delta = new_uncomp_size - uncomp_size
    new_buf_size = old_buf_size + buf_delta
    content = re.sub(r'(\.lvglFontBufSize\s*=\s*)\d+', r'\g<1>' + str(new_buf_size), content)

    # Write
    with open(c_file_path, 'w') as f:
        f.write(content)

    ratio = (new_comp_size * 100) // new_uncomp_size if new_uncomp_size else 0
    print(f"  Fixed: uncomp {uncomp_size}->{new_uncomp_size}, comp {comp_size}->{new_comp_size}, "
          f"bitmap_ofs {old_bitmap_ofs}->{new_bitmap_ofs}, buf {old_buf_size}->{new_buf_size}, ratio={ratio}%")
    return True


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 fix_dseg7_glyph.py <c_file_or_dir>")
        sys.exit(1)

    path = sys.argv[1]
    if os.path.isdir(path):
        files = sorted(f for f in os.listdir(path) if f.startswith('lv_font_dseg7') and f.endswith('.c'))
        if not files:
            print(f"No DSEG7 font files found in {path}")
            sys.exit(1)
        cfiles = [os.path.join(path, f) for f in files]
    else:
        cfiles = [path]

    for cf in cfiles:
        print(f"Repairing {cf}...")
        repair_font_c(cf)


if __name__ == '__main__':
    main()
