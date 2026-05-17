#!/usr/bin/env python3
"""
Convert LVGL font output (lv_font.inc from lv_font_conv) to EdgeTX LZ4-compressed format.
Usage:
    lv_font_conv --no-prefilter --bpp 4 --size N --font font.ttf -r CHARS \\
        --format lvgl -o lv_font.inc --force-fast-kern-format --no-compress
    python3 lz4_font.py <output_name> [--no-kern]
"""

import struct
import sys
import os
import re
import lz4.block


def parse_c_array(content):
    """Extract comma-separated hex/int values from a C array like '{ 0x00, 0x01, ... }'."""
    # Remove comments
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    vals = []
    for m in re.finditer(r'0x[0-9a-fA-F]+|\d+', content):
        v = int(m.group(0), 0)
        vals.append(v)
    return vals


def parse_glyph_dsc_array(content):
    """Parse glyph_dsc array entries with designated initializers."""
    dscs = []
    # Match each {...}, entry
    entries = re.finditer(
        r'\{\s*\.bitmap_index\s*=\s*(\d+)\s*,?\s*'
        r'\.\s*adv_w\s*=\s*(\d+)\s*,?\s*'
        r'\.\s*box_w\s*=\s*(\d+)\s*,?\s*'
        r'\.\s*box_h\s*=\s*(\d+)\s*,?\s*'
        r'\.\s*ofs_x\s*=\s*([-]?\d+)\s*,?\s*'
        r'\.\s*ofs_y\s*=\s*([-]?\d+)\s*\}',
        content)
    for m in entries:
        dscs.append({
            'bitmap_index': int(m.group(1)),
            'adv_w': int(m.group(2)),
            'box_w': int(m.group(3)),
            'box_h': int(m.group(4)),
            'ofs_x': int(m.group(5)),
            'ofs_y': int(m.group(6)),
        })
    return dscs


CMAP_TYPE_MAP = {
    'LV_FONT_FMT_TXT_CMAP_FORMAT0_TINY': 0,
    'LV_FONT_FMT_TXT_CMAP_FORMAT0_FULL': 1,
    'LV_FONT_FMT_TXT_CMAP_SPARSE_TINY': 2,
    'LV_FONT_FMT_TXT_CMAP_SPARSE_FULL': 3,
}


def parse_cmaps(content):
    """Parse cmaps array entries."""
    cmaps = []
    entries = re.finditer(
        r'\{\s*\.range_start\s*=\s*(\d+)\s*,?\s*'
        r'\.\s*range_length\s*=\s*(\d+)\s*,?\s*'
        r'\.\s*glyph_id_start\s*=\s*(\d+)\s*,?\s*'
        r'\.\s*unicode_list\s*=\s*(NULL|[a-zA-Z_]\w*)\s*,?\s*'
        r'\.\s*glyph_id_ofs_list\s*=\s*(NULL|[a-zA-Z_]\w*)\s*,?\s*'
        r'\.\s*list_length\s*=\s*(\d+)\s*,?\s*'
        r'\.\s*type\s*=\s*(\d+|LV_\w+)',
        content, re.DOTALL)
    for m in entries:
        type_str = m.group(7)
        if type_str.isdigit():
            type_val = int(type_str)
        elif type_str in CMAP_TYPE_MAP:
            type_val = CMAP_TYPE_MAP[type_str]
        else:
            type_val = 0
        cmaps.append({
            'range_start': int(m.group(1)),
            'range_length': int(m.group(2)),
            'glyph_id_start': int(m.group(3)),
            'unicode_list_name': m.group(4),
            'glyph_id_ofs_list_name': m.group(5),
            'list_length': int(m.group(6)),
            'type': type_val,
        })
    return cmaps


def extract_uint16_array(content, name):
    """Extract a uint16_t array by its variable name."""
    pat = re.compile(
        r'static\s+const\s+uint16_t\s+' + re.escape(name) + r'\[\]\s*=\s*\{([^}]+)\}',
        re.DOTALL)
    m = pat.search(content)
    if not m:
        return None
    return parse_c_array(m.group(1))


def extract_uint8_array(content, name):
    """Extract a uint8_t array by its variable name."""
    pat = re.compile(
        r'(?:static\s+)?(?:LV_ATTRIBUTE_LARGE_CONST\s+)?const\s+uint8_t\s+' +
        re.escape(name) + r'\[\]\s*=\s*\{([^}]+)\}',
        re.DOTALL)
    m = pat.search(content)
    if not m:
        return None
    return parse_c_array(m.group(1))


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 lz4_font.py <output_name> [--no-kern]")
        sys.exit(1)

    output_name = sys.argv[1]
    no_kern = '--no-kern' in sys.argv

    inc_file = 'lv_font.inc'
    if not os.path.exists(inc_file):
        # Try script directory
        inc_file = os.path.join(os.path.dirname(__file__), 'lv_font.inc')
    if not os.path.exists(inc_file):
        print(f"ERROR: {inc_file} not found. Run lv_font_conv first.")
        sys.exit(1)

    with open(inc_file, 'r') as f:
        content = f.read()

    # ---- Extract data from C source ----

    # lv_font properties
    def extract_font_prop(name):
        m = re.search(r'\.' + re.escape(name) + r'\s*=\s*(-?\d+)', content)
        return int(m.group(1)) if m else 0

    # line_height, base_line, etc.
    line_height = extract_font_prop('line_height')
    base_line = extract_font_prop('base_line')

    subpx_match = re.search(r'\.subpx\s*=\s*(\w+)', content)
    subpx = 0
    if subpx_match:
        val = subpx_match.group(1)
        if val.isdigit():
            subpx = int(val)
    underline_position = extract_font_prop('underline_position')
    underline_thickness = extract_font_prop('underline_thickness')

    # font_dsc properties
    kern_scale = 0
    cmap_num = 0
    bpp = 4
    kern_classes = 0
    bitmap_format = 0

    dsc_match = re.search(r'static\s+const\s+lv_font_fmt_txt_dsc_t\s+font_dsc\s*=', content)
    if not dsc_match:
        dsc_match = re.search(r'static\s+lv_font_fmt_txt_dsc_t\s+font_dsc\s*=', content)

    if dsc_match:
        dsc_content = content[dsc_match.end():]
        # Find the matching closing brace
        depth = 1
        i = 0
        while depth > 0 and i < len(dsc_content):
            if dsc_content[i] == '{':
                depth += 1
            elif dsc_content[i] == '}':
                depth -= 1
            i += 1
        dsc_body = dsc_content[:i]

        for m in re.finditer(r'\.(\w+)\s*=\s*([^,;]+)', dsc_body):
            key = m.group(1)
            val = m.group(2).strip()
            if key == 'kern_scale':
                kern_scale = int(val)
            elif key == 'cmap_num':
                cmap_num = int(val)
            elif key == 'bpp':
                bpp = int(val)
            elif key == 'kern_classes':
                kern_classes = int(val)
            elif key == 'bitmap_format':
                bitmap_format = int(val)

    # ---- Parse structures ----
    glyph_dsc_list = parse_glyph_dsc_array(content)
    cmaps_list = parse_cmaps(content)

    # Extract glyph_bitmap bytes
    glyph_bitmap = extract_uint8_array(content, 'glyph_bitmap')

    # Extract unicode lists
    unicode_lists = {}
    for cm in cmaps_list:
        name = cm['unicode_list_name']
        if name and name != 'NULL':
            arr = extract_uint16_array(content, name)
            if arr:
                unicode_lists[name] = arr

    glyph_id_ofs_lists = {}
    for cm in cmaps_list:
        name = cm['glyph_id_ofs_list_name']
        if name and name != 'NULL':
            arr = extract_uint8_array(content, name)
            if arr:
                glyph_id_ofs_lists[name] = arr

    # ---- Build uncompressed data buffer ----
    # Order: glyph_dsc, cmap lists, glyph_bitmap (no kern for DSEG7)
    uncomp_data = bytearray()

    # 1. glyph_dsc array (16 bytes per entry: uint32_t+uint32_t+uint16_t+uint16_t+int16_t+int16_t)
    for gd in glyph_dsc_list:
        uncomp_data += struct.pack('<IIHHhh',
                                   gd['bitmap_index'],
                                   gd['adv_w'],
                                   gd['box_w'],
                                   gd['box_h'],
                                   gd['ofs_x'],
                                   gd['ofs_y'])

    # 2. cmap lists (unicode_list and glyph_id_ofs_list)
    etx_cmaps = []
    for cm in cmaps_list:
        ecm = {
            'range_start': cm['range_start'],
            'range_length': cm['range_length'],
            'glyph_id_start': cm['glyph_id_start'],
            'list_length': cm['list_length'],
            'type': cm['type'],
            'unicode_list_ofs': 0,
            'glyph_id_ofs_list_ofs': 0,
        }

        name = cm['unicode_list_name']
        if name and name != 'NULL' and name in unicode_lists:
            ecm['unicode_list_ofs'] = len(uncomp_data)
            for v in unicode_lists[name]:
                uncomp_data += struct.pack('<H', v)

        name = cm['glyph_id_ofs_list_name']
        if name and name != 'NULL' and name in glyph_id_ofs_lists:
            ecm['glyph_id_ofs_list_ofs'] = len(uncomp_data)
            uncomp_data += bytes(glyph_id_ofs_lists[name])

        etx_cmaps.append(ecm)

    # 3. glyph_bitmap
    glyph_bitmap_ofs = len(uncomp_data)
    uncomp_data += bytes(glyph_bitmap)

    # ---- LZ4 compress ----
    comp_data = lz4.block.compress(bytes(uncomp_data), mode='high_compression',
                                    store_size=False)

    # ---- Extract bare C identifier from output name ----
    base_name = os.path.basename(output_name)
    # If name starts with something like "std/lv_font_", extract the font part
    font_name_parts = re.split(r'[/\\]', output_name)
    font_var_part = font_name_parts[-1]
    # The C variable name: strip "lv_font_" prefix if present
    c_var = font_var_part
    if c_var.startswith('lv_font_'):
        c_var = c_var[8:]  # remove 'lv_font_' prefix

    # ---- Calculate buffer size for decompression ----
    buf_size = (len(uncomp_data) +
                68 +  # sizeof(lv_font_t) approximate
                32 +  # sizeof(lv_font_fmt_txt_dsc_t)
                32 +  # sizeof(lv_font_fmt_txt_glyph_cache_t)
                cmap_num * 20 +  # sizeof(lv_font_fmt_txt_cmap_t)
                (0 if no_kern else (32 if kern_classes else 0)))

    # ---- Write output .c file ----
    out_path = output_name + '.c'
    with open(out_path, 'w') as f:
        f.write('#include "definitions.h"\n')
        f.write('#include "lz4_fonts.h"\n\n')

        # Compressed data array
        f.write('static const uint8_t lz4FontData[] __FLASH = {\n')
        for i, b in enumerate(comp_data):
            f.write(f'0x{b:02x},')
            if (i & 0x0F) == 0x0F:
                f.write('\n')
        if (len(comp_data) & 0x0F) != 0:
            f.write('\n')
        f.write('};\n\n')

        # Cmaps
        if cmaps_list:
            f.write('static const etxFontCmap cmaps[] __FLASH = {\n')
            for ecm in etx_cmaps:
                f.write(f'{{ .range_start = {ecm["range_start"]}, '
                        f'.range_length = {ecm["range_length"]}, '
                        f'.glyph_id_start = {ecm["glyph_id_start"]}, '
                        f'.list_length = {ecm["list_length"]}, '
                        f'.type = {ecm["type"]}, '
                        f'.unicode_list = {ecm["unicode_list_ofs"]}, '
                        f'.glyph_id_ofs_list = {ecm["glyph_id_ofs_list_ofs"]} }},\n')
            f.write('};\n\n')

        # etxLz4Font structure
        f.write(f'const etxLz4Font lv_font_{c_var} __FLASH = {{\n')
        f.write(f'.uncomp_size = {len(uncomp_data)},\n')
        f.write(f'.comp_size = {len(comp_data)},\n')
        f.write(f'.line_height = {line_height},\n')
        f.write(f'.base_line = {base_line},\n')
        f.write(f'.subpx = {subpx},\n')
        f.write(f'.underline_position = {underline_position},\n')
        f.write(f'.underline_thickness = {underline_thickness},\n')
        f.write(f'.kern_scale = {kern_scale},\n')
        f.write(f'.cmap_num = {cmap_num},\n')
        f.write(f'.bpp = {bpp},\n')
        f.write(f'.kern_classes = {kern_classes},\n')
        f.write(f'.bitmap_format = {bitmap_format},\n')
        f.write(f'.left_class_cnt = 0,\n')
        f.write(f'.right_class_cnt = 0,\n')
        f.write(f'.glyph_bitmap = {glyph_bitmap_ofs},\n')
        f.write(f'.class_pair_values = 0,\n')
        f.write(f'.left_class_mapping = 0,\n')
        f.write(f'.right_class_mapping = 0,\n')
        f.write(f'.cmaps = cmaps,\n')
        f.write(f'.compressed = lz4FontData,\n')
        f.write(f'.lvglFontBufSize = {buf_size},\n')
        f.write('};\n')

    ratio = (len(comp_data) * 100) // len(uncomp_data) if uncomp_data else 0
    print(f'{output_name} {len(uncomp_data)} {len(comp_data)} {ratio}%')
    print(f'Wrote {out_path}')


if __name__ == '__main__':
    main()
