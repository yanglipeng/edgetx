/*
 * Copyright (C) EdgeTX
 *
 * Based on code named
 *   opentx - https://github.com/opentx/opentx
 *   th9x - http://code.google.com/p/th9x
 *   er9x - http://code.google.com/p/er9x
 *   gruvin9x - http://code.google.com/p/gruvin9x
 *
 * License GPLv2: http://www.gnu.org/licenses/gpl-2.0.html
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License version 2 as
 * published by the Free Software Foundation.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * Heli instrument fonts — separate from the main UI font system.
 * Loaded on-demand via getHeliFont(), decompressed into SDRAM.
 * Intended for Lua-based helicopter instrument panel scripts.
 */

#include "heli_fonts.h"
#include "lz4/lz4.h"
#include "lz4_fonts.h"

#include <cstdlib>
#include <cstring>
#include <unistd.h>

#if !defined(BOOT)

extern "C" {

extern const etxLz4Font lv_font_dseg7_32;
extern const etxLz4Font lv_font_dseg7_48;
extern const etxLz4Font lv_font_dseg7_64;
extern const etxLz4Font lv_font_dseg7_bold_32;
extern const etxLz4Font lv_font_dseg7_bold_48;
extern const etxLz4Font lv_font_dseg7_bold_64;

} // extern "C"

struct etxHeliFont {
  const etxLz4Font* lz4Font;
  lv_font_t*        lvglFont;
  bool              loaded;
};

#define HELI_BUFSIZE(x) (((x) + 15) & 0xFFFFFFF0)

static etxHeliFont heliFontTable[HELI_FONTS_COUNT] = {
  { &lv_font_dseg7_32,      nullptr, false },
  { &lv_font_dseg7_48,      nullptr, false },
  { &lv_font_dseg7_64,      nullptr, false },
  { &lv_font_dseg7_bold_32, nullptr, false },
  { &lv_font_dseg7_bold_48, nullptr, false },
  { &lv_font_dseg7_bold_64, nullptr, false },
};

static bool heliFontAllocFailed = false;

static void initHeliFontBuffers()
{
  if (heliFontTable[0].lvglFont || heliFontAllocFailed) return;

  int sz = 0;
  for (int i = 0; i < HELI_FONTS_COUNT; i += 1) {
    if (heliFontTable[i].lz4Font) {
      sz += HELI_BUFSIZE(heliFontTable[i].lz4Font->lvglFontBufSize);
    }
  }

#if defined(SIMU)
  uint8_t* b = (uint8_t*)malloc(sz);
#else
  uint8_t* b = (uint8_t*)sbrk(sz);
#endif

  if (b) {
    for (int i = 0; i < HELI_FONTS_COUNT; i += 1) {
      if (heliFontTable[i].lz4Font) {
        heliFontTable[i].lvglFont = (lv_font_t*)b;
        b += HELI_BUFSIZE(heliFontTable[i].lz4Font->lvglFontBufSize);
      }
    }
  } else {
    heliFontAllocFailed = true;
  }
}

static void decompressHeliFont(int idx)
{
  if (idx < 0 || idx >= HELI_FONTS_COUNT) return;
  if (heliFontTable[idx].loaded) return;

  const etxLz4Font* etxFont = heliFontTable[idx].lz4Font;
  if (!etxFont) return;

  initHeliFontBuffers();
  if (heliFontAllocFailed) return;

  uint8_t* data = (uint8_t*)heliFontTable[idx].lvglFont;
  memset(data, 0, etxFont->lvglFontBufSize);

  uint8_t* next = data;

  // lv_font_t structure
  lv_font_t* lvglFont = (lv_font_t*)next;
  next += sizeof(lv_font_t);

  // lv_font_fmt_txt_dsc_t structure
  lv_font_fmt_txt_dsc_t* lvglFontDsc = (lv_font_fmt_txt_dsc_t*)next;
  next += sizeof(lv_font_fmt_txt_dsc_t);

  // glyph cache
  lv_font_fmt_txt_glyph_cache_t* lvglCache =
      (lv_font_fmt_txt_glyph_cache_t*)next;
  next += sizeof(lv_font_fmt_txt_glyph_cache_t);

  // optional kern classes
  lv_font_fmt_txt_kern_classes_t* lvglKernClasses = nullptr;
  if (etxFont->kern_classes) {
    lvglKernClasses = (lv_font_fmt_txt_kern_classes_t*)next;
    next += sizeof(lv_font_fmt_txt_kern_classes_t);
  }

  // cmap array
  lv_font_fmt_txt_cmap_t* lvglCmaps = (lv_font_fmt_txt_cmap_t*)next;
  next += sizeof(lv_font_fmt_txt_cmap_t) * etxFont->cmap_num;

  // decompress glyph data
  int lz4_ret = LZ4_decompress_safe((const char*)etxFont->compressed, (char*)next,
                                    etxFont->comp_size, etxFont->uncomp_size);
  if (lz4_ret < 0) {
    heliFontTable[idx].loaded = true;
    return;
  }

  // rebuild lv_font_t
  lvglFont->get_glyph_dsc = lv_font_get_glyph_dsc_fmt_txt;
  lvglFont->get_glyph_bitmap = lv_font_get_bitmap_fmt_txt;
  lvglFont->dsc = lvglFontDsc;
  lvglFont->line_height = etxFont->line_height;
  lvglFont->base_line = etxFont->base_line;
  lvglFont->subpx = etxFont->subpx;
  lvglFont->underline_position = etxFont->underline_position;
  lvglFont->underline_thickness = etxFont->underline_thickness;

  // rebuild lv_font_fmt_txt_dsc_t
  lvglFontDsc->glyph_bitmap = &next[etxFont->glyph_bitmap];
  lvglFontDsc->glyph_dsc = (lv_font_fmt_txt_glyph_dsc_t*)&next[0];
  lvglFontDsc->cmaps = lvglCmaps;
  lvglFontDsc->kern_dsc = lvglKernClasses;
  lvglFontDsc->kern_classes = etxFont->kern_classes;
  lvglFontDsc->bitmap_format = etxFont->bitmap_format;
  lvglFontDsc->cache = lvglCache;
  lvglFontDsc->kern_scale = etxFont->kern_scale;
  lvglFontDsc->cmap_num = etxFont->cmap_num;
  lvglFontDsc->bpp = etxFont->bpp;

  // rebuild kern classes (if present)
  if (etxFont->kern_classes) {
    lvglKernClasses->class_pair_values =
        (int8_t*)&next[etxFont->class_pair_values];
    lvglKernClasses->left_class_mapping = &next[etxFont->left_class_mapping];
    lvglKernClasses->right_class_mapping = &next[etxFont->right_class_mapping];
    lvglKernClasses->left_class_cnt = etxFont->left_class_cnt;
    lvglKernClasses->right_class_cnt = etxFont->right_class_cnt;
  }

  // rebuild cmaps
  for (int i = 0; i < etxFont->cmap_num; i += 1) {
    if (etxFont->cmaps[i].unicode_list)
      lvglCmaps[i].unicode_list =
          (uint16_t*)&next[etxFont->cmaps[i].unicode_list];
    if (etxFont->cmaps[i].glyph_id_ofs_list)
      lvglCmaps[i].glyph_id_ofs_list =
          &next[etxFont->cmaps[i].glyph_id_ofs_list];
    lvglCmaps[i].range_start = etxFont->cmaps[i].range_start;
    lvglCmaps[i].range_length = etxFont->cmaps[i].range_length;
    lvglCmaps[i].glyph_id_start = etxFont->cmaps[i].glyph_id_start;
    lvglCmaps[i].list_length = etxFont->cmaps[i].list_length;
    lvglCmaps[i].type = etxFont->cmaps[i].type;
  }

  heliFontTable[idx].loaded = true;
}

const lv_font_t* getHeliFont(HeliFontId id)
{
  if (id >= HELI_FONTS_COUNT) return nullptr;
  decompressHeliFont((int)id);
  return heliFontTable[id].lvglFont;
}

#endif // !BOOT
