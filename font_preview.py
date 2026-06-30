#!/usr/bin/env python3
"""Render DSEG7 font bitmaps to a PNG image for visual verification."""
import struct, sys, re, lz4.block
from PIL import Image

def parse_c_array(content, name):
    pat = re.compile(r'(?:static\s+)?(?:const\s+)?uint8_t\s+' + re.escape(name) +
                     r'\[\]\s*[^\{]*\{\s*([^}]+)\}', re.DOTALL)
    m = pat.search(content)
    if not m: return None
    vals = []
    for v in re.finditer(r'0x[0-9a-fA-F]+|\d+', m.group(1)):
        vals.append(int(v.group(0), 0))
    return vals

def get_int(content, name):
    m = re.search(r'\.' + re.escape(name) + r'\s*=\s*(\d+)', content)
    return int(m.group(1)) if m else 0

def parse_cmaps(content):
    m = re.search(r'etxFontCmap\s+cmaps\[\]\s*__FLASH\s*=\s*\{(.*?)\};', content, re.DOTALL)
    if not m: return None
    cmap_body = m.group(1)
    cmaps = []
    for cm in re.finditer(
        r'\{\s*\.range_start\s*=\s*(\d+)\s*,\s*\.range_length\s*=\s*(\d+)\s*,'
        r'\s*\.glyph_id_start\s*=\s*(\d+)\s*,\s*\.list_length\s*=\s*(\d+)\s*,'
        r'\s*\.type\s*=\s*(\d+)\s*,\s*\.unicode_list\s*=\s*(\d+)\s*,'
        r'\s*\.glyph_id_ofs_list\s*=\s*(\d+)\s*\}', cmap_body):
        cmaps.append({
            'range_start': int(cm.group(1)),
            'range_length': int(cm.group(2)),
            'glyph_id_start': int(cm.group(3)),
            'list_length': int(cm.group(4)),
            'type': int(cm.group(5)),
            'unicode_list_ofs': int(cm.group(6)),
            'glyph_id_ofs_list_ofs': int(cm.group(7)),
        })
    return cmaps

def lookup_glyph(cmaps, codepoint, raw):
    for cm in cmaps:
        rstart = cm['range_start']
        rend = rstart + cm['range_length']
        if codepoint >= rstart and codepoint < rend:
            rcp = codepoint - rstart
            if cm['type'] == 0:
                return cm['glyph_id_start'] + rcp
            elif cm['type'] == 2:
                if cm['unicode_list_ofs']:
                    ofs = cm['unicode_list_ofs']
                    for i in range(cm['list_length']):
                        u_val = struct.unpack_from('<H', raw, ofs)[0]
                        if u_val == rcp:
                            return cm['glyph_id_start'] + i
                        ofs += 2
                return 0
            elif cm['type'] == 1:
                if cm['unicode_list_ofs']:
                    ofs = cm['unicode_list_ofs']
                    for i in range(cm['list_length']):
                        u_val = struct.unpack_from('<H', raw, ofs)[0]
                        if u_val == rcp:
                            if cm['glyph_id_ofs_list_ofs']:
                                g_ofs = cm['glyph_id_ofs_list_ofs']
                                return cm['glyph_id_start'] + raw[g_ofs + i]
                            return cm['glyph_id_start'] + i
                        ofs += 2
                return 0
            elif cm['type'] == 3:
                if cm['glyph_id_ofs_list_ofs']:
                    return cm['glyph_id_start'] + raw[cm['glyph_id_ofs_list_ofs'] + rcp]
                return cm['glyph_id_start'] + rcp
    return 0

def decode_4bpp(data, w, h):
    pixels = []
    stride = (w + 1) // 2
    for row in range(h):
        row_start = row * stride
        for col in range(w):
            byte_idx = row_start + col // 2
            if byte_idx < len(data):
                byte_val = data[byte_idx]
                px = (byte_val >> 4) & 0x0F if col % 2 == 0 else byte_val & 0x0F
            else:
                px = 0
            pixels.append(px * 17)
    return pixels

def main():
    if len(sys.argv) < 2:
        print("Usage: font_preview.py <font.c> [output.png]")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        content = f.read()

    out_file = sys.argv[2] if len(sys.argv) > 2 else 'font_preview.png'

    uncomp_size = get_int(content, 'uncomp_size')
    gb_ofs = get_int(content, 'glyph_bitmap')
    line_h = get_int(content, 'line_height')
    base = get_int(content, 'base_line')
    bpp = get_int(content, 'bpp')

    print(f"Font: {sys.argv[1]}")
    print(f"  uncomp_size={uncomp_size}, line_height={line_h}, base_line={base}, bpp={bpp}")
    print(f"  glyph_bitmap_offset={gb_ofs}")

    comp = parse_c_array(content, 'lz4FontData')
    if not comp:
        print("ERROR: cannot parse lz4FontData"); sys.exit(1)
    try:
        raw = lz4.block.decompress(bytes(comp), uncompressed_size=uncomp_size)
    except:
        raw = lz4.block.decompress(bytes(comp))
    print(f"  decompressed: {len(raw)} (expected {uncomp_size})")

    # glyph_dsc entries (8 bytes each)
    glyphs = []
    off = 0
    while off + 8 <= gb_ofs:
        pk = struct.unpack_from('<I', raw, off)[0]
        bm_idx = pk & 0xFFFFF
        adv_w = (pk >> 20) & 0xFFF
        box_w = raw[off+4]; box_h = raw[off+5]
        ofs_x = raw[off+6] - 256 if raw[off+6] > 127 else raw[off+6]
        ofs_y = raw[off+7] - 256 if raw[off+7] > 127 else raw[off+7]
        glyphs.append((bm_idx, adv_w, box_w, box_h, ofs_x, ofs_y))
        off += 8
    print(f"  glyphs: {len(glyphs)}")

    bm_data = raw[gb_ofs:]
    print(f"  bitmap bytes: {len(bm_data)}")

    cmaps = parse_cmaps(content)
    if cmaps:
        chars = [(0x20,' '),(0x21,'!'),(0x22,'"'),(0x2D,'-'),(0x2E,'.')] + \
                [(0x30+i,chr(0x30+i)) for i in range(10)] + \
                [(0x3A,':')] + [(0x41+i,chr(0x41+i)) for i in range(6)]

        print(f"\n  Glyph lookup and rendering:")
        rows = []
        max_row_w = 0
        total_h = 8
        for cp, ch in chars:
            gid = lookup_glyph(cmaps, cp, raw) if cmaps else 0
            if gid < len(glyphs):
                bm_idx, adv_w, box_w, box_h, ofs_x, ofs_y = glyphs[gid]
                print(f"    U+{cp:04X} '{ch}' -> gid={gid} bm={bm_idx} adv={adv_w} "
                      f"box={box_w}x{box_h} ofs=({ofs_x},{ofs_y})")
                if box_w > 0 and box_h > 0:
                    px = decode_4bpp(bm_data[bm_idx:], box_w, box_h)
                    img = Image.new('RGBA', (box_w, box_h), (40,40,40,255))
                    for y in range(box_h):
                        for x in range(box_w):
                            a = px[y*box_w+x]
                            if a > 0:
                                r = 200*a//255 + 30; g = 255*a//255 + 30; b = 100*a//255 + 30
                                img.putpixel((x,y), (r,g,b,255))
                    rows.append((cp, ch, img))
                    max_row_w = max(max_row_w, img.width)
                    total_h += img.height + 8
        if rows:
            max_row_w = max(max_row_w, 300)
            canvas = Image.new('RGBA', (max_row_w+16, total_h), (40,40,40,255))
            y = 8
            for cp, ch, img in rows:
                canvas.paste(img, (8, y))
                y += img.height + 8
            canvas.save(out_file)
            print(f"\n  Saved: {out_file}")

if __name__ == '__main__':
    main()
