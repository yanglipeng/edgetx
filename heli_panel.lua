--[[
  heli_panel.lua — EdgeTX Tool Script (color LCD)
  Helicopter HUD instrument panel showcasing all 6 DSEG7 7-segment fonts.
  Designed for TX16S (480×272).

  Place in /SCRIPTS/TOOLS/ on SD card.
  Run from radio: Models → [pick a model] → Scripts → heli_panel
]]

------------------------------
-- DSEG7 fonts via heliFont()
-- 0=d32  1=d48  2=d64
-- 3=b32  4=b48  5=b64
------------------------------
local F = {
  d32 = lvgl.heliFont(0),
  d48 = lvgl.heliFont(1),
  d64 = lvgl.heliFont(2),
  b32 = lvgl.heliFont(3),
  b48 = lvgl.heliFont(4),
  b64 = lvgl.heliFont(5),
}

-- (check deferred to run() so LVGL context is ready)

------------------------------
-- Color palette
-- Aviation HUD: green primary,
-- cyan info, yellow caution, red warning
------------------------------
local C = {
  bg      = lcd.RGB(6, 8, 14),       -- deep cockpit black
  panel   = lcd.RGB(12, 16, 26),     -- panel surface
  border  = lcd.RGB(28, 34, 46),     -- subtle separators
  label   = lcd.RGB(130, 140, 150),  -- descriptor text
  white   = lcd.RGB(230, 237, 243),
  green   = lcd.RGB(63, 185, 80),
  cyan    = lcd.RGB(88, 166, 255),
  yellow  = lcd.RGB(210, 153, 34),
  red     = lcd.RGB(248, 81, 73),
  magenta = lcd.RGB(188, 140, 255),
  dim     = lcd.RGB(70, 78, 90),     -- legend text
}

------------------------------
-- Color helpers with thresholds
------------------------------
local function rpmCol(rpm)
  if rpm > 3200 then return C.red end
  if rpm > 3000 then return C.yellow end
  if rpm < 1800 then return C.yellow end
  return C.green
end
local function altCol(alt)
  if alt > 3000 then return C.red end
  if alt > 2000 then return C.yellow end
  return C.green
end
local function spdCol(spd)
  return spd > 120 and C.yellow or (spd > 140 and C.red or C.green)
end
local function voltCol(v)
  return v < 3.5 and C.red or (v < 3.8 and C.yellow or C.green)
end
local function tempCol(t)
  return t > 105 and C.red or (t > 92 and C.yellow or C.green)
end
local function fuelCol(f)
  return f < 20 and C.red or (f < 35 and C.yellow or C.green)
end
local function vrtCol(v)
  return math.abs(v) > 3 and C.yellow or C.green
end

------------------------------
-- Simulated telemetry
-- (evaluated per-frame, data
--  shared across all callbacks)
------------------------------
local t0 = os.clock()
local sim = {}
local function updateSim()
  local t = os.clock() - t0
  sim.alt   = 1000 + 450 * math.sin(t * 0.25)
  sim.rpm   = 2680 + 220 * math.sin(t * 0.45) + 30 * math.sin(t * 1.7)
  sim.spd   = 82 + 28 * math.sin(t * 0.18)
  sim.volt  = (4.18 - 0.08 * math.sin(t * 0.08)) % 4.22
  sim.hdg   = (180 + 40 * math.sin(t * 0.07)) % 360
  sim.fuel  = math.max(0, 62 - 2.5 * math.sin(t * 0.04))
  sim.vrt   = 2.4 * math.sin(t * 0.35)
  sim.timer = t
  sim.temp  = 88 + 6 * math.sin(t * 0.12)
end

------------------------------
-- Format helpers
------------------------------
local function pad(n, d)
  local s = tostring(math.max(0, math.floor(n)))
  while #s < d do s = "0" .. s end
  return s
end

------------------------------
-- One-shot UI construction
------------------------------
local built = false

local function buildUI()
  if built then return end

  -- full-screen background
  lvgl.rectangle{x = 0, y = 0, w = 480, h = 272,
                 color = C.bg, filled = true}

  -- title bar
  lvgl.label{x = 0, y = 3, w = 480, h = 14,
             text = "HELI INSTRUMENT PANEL  ·  DSEG7 FONT SHOWCASE",
             color = C.cyan, align = 0x04}
  lvgl.rectangle{x = 0, y = 18, w = 480, h = 1,
                 color = C.border, filled = true}

  --[[==========================================================
    Row 1 — Main instruments  (y=22 … y=180, h=158)
  ==========================================================]]
  local y1, h1 = 22, 158

  -- Helper: panel background
  local function panel(x, y, w, h)
    lvgl.rectangle{x = x, y = y, w = w, h = h,
                   color = C.panel, filled = true, rounded = 3}
    lvgl.rectangle{x = x, y = y, w = w, h = h,
                   color = C.border, thickness = 1, rounded = 3}
  end

  -- Helper: DSEG7 numeric gauge
  local function gauge(x, y, w, h, label, fnValue, fnColor, fnDigits, dsegFont)
    lvgl.label{x = x, y = y + 4, w = w, h = 18,
               text = label, color = C.label, align = 0x04}
    local v = lvgl.label{x = x, y = y + 28, w = w, h = dsegFont == F.b64 and 72 or 56,
               text = function() return pad(fnValue(sim), fnDigits) end,
               color = function() return fnColor(sim) end,
               align = 0x04}
    lvgl.setFont(v, dsegFont)
  end

  ---------- ALT ----------
  panel(5, y1, 115, h1)
  gauge(5, y1, 115, h1, "ALT",   function(d) return d.alt end, altCol, 5, F.b48)
  lvgl.label{x = 5, y = y1 + h1 - 20, w = 115, h = 16,
             text = "ft", color = C.label, align = 0x04}

  ---------- RPM (centre, with arc gauge) ----------
  panel(124, y1, 114, h1)
  lvgl.label{x = 124, y = y1 + 4, w = 114, h = 18,
             text = "RPM", color = C.label, align = 0x04}

  -- arc track behind RPM value
  local arcCX, arcCY = 124 + 57, y1 + h1 / 2 + 4
  local arcR = 44
  lvgl.arc{x = arcCX - arcR - 4, y = arcCY - arcR - 4,
           w = (arcR + 4) * 2, h = (arcR + 4) * 2,
           radius = arcR, thickness = 5,
           startAngle = 135, endAngle = 405,
           bgStartAngle = 135, bgEndAngle = 405,
           bgColor = C.border, bgOpacity = 180,
           color = C.border, rounded = true}
  lvgl.arc{x = arcCX - arcR - 4, y = arcCY - arcR - 4,
           w = (arcR + 4) * 2, h = (arcR + 4) * 2,
           radius = arcR, thickness = 5,
           startAngle = 135,
           endAngle = function()
             return 135 + 270 * math.min(sim.rpm / 3500, 1)
           end,
           color = function() return rpmCol(sim.rpm) end,
           rounded = true}

  -- RPM value on top of arc
  local rpmDisp = lvgl.label{
    x = 124, y = arcCY - 28, w = 114, h = 56,
    text = function() return pad(sim.rpm, 4) end,
    color = function() return rpmCol(sim.rpm) end,
    align = 0x04}
  lvgl.setFont(rpmDisp, F.b64)

  lvgl.label{x = 124, y = y1 + h1 - 20, w = 114, h = 16,
             text = "rpm", color = C.label, align = 0x04}

  ---------- SPD ----------
  panel(242, y1, 115, h1)
  gauge(242, y1, 115, h1, "SPD", function(d) return d.spd end, spdCol, 3, F.b48)
  lvgl.label{x = 242, y = y1 + h1 - 20, w = 115, h = 16,
             text = "km/h", color = C.label, align = 0x04}

  ---------- HEAD ----------
  panel(361, y1, 114, h1)
  lvgl.label{x = 361, y = y1 + 4, w = 114, h = 18,
             text = "HEAD", color = C.label, align = 0x04}
  local hdgDisp = lvgl.label{
    x = 361, y = y1 + 36, w = 114, h = 50,
    text = function() return pad(sim.hdg, 3) end,
    color = C.cyan, align = 0x04}
  lvgl.setFont(hdgDisp, F.b32)

  -- compass cardinal
  local cardinals = {"N","NE","E","SE","S","SW","W","NW"}
  lvgl.label{x = 361, y = y1 + h1 - 20, w = 114, h = 16,
    text = function()
      return cardinals[(math.floor((sim.hdg + 22.5) / 45) % 8) + 1]
    end,
    color = C.label, align = 0x04}

  --[[==========================================================
    Row 2 — Secondary instruments  (y=185 … y=256, h=71)
  ==========================================================]]
  local y2, h2 = 186, 70

  lvgl.rectangle{x = 0, y = y2 - 3, w = 480, h = 1,
                 color = C.border, filled = true}

  local sec = {
    { x = 5, w = 92, label = "VOLT",
      value = function() return string.format("%.2f", sim.volt) end,
      color = function() return voltCol(sim.volt) end,
      unit = "V" },
    { x = 101, w = 92, label = "FUEL",
      value = function() return pad(sim.fuel, 2) end,
      color = function() return fuelCol(sim.fuel) end,
      unit = "%" },
    { x = 197, w = 92, label = "VRT",
      value = function()
        local v = sim.vrt
        return (v >= 0 and " " or "") .. string.format("%.1f", v)
      end,
      color = function() return vrtCol(sim.vrt) end,
      unit = "m/s" },
    { x = 293, w = 92, label = "TIME",
      value = function()
        local s = math.floor(sim.timer)
        return pad(math.floor(s / 60), 2) .. ":" .. pad(s % 60, 2)
      end,
      color = function() return C.cyan end,
      unit = "" },
    { x = 389, w = 86, label = "TEMP",
      value = function() return pad(sim.temp, 2) end,
      color = function() return tempCol(sim.temp) end,
      unit = "°C" },
  }

  for _, g in ipairs(sec) do
    panel(g.x, y2, g.w, h2)

    lvgl.label{x = g.x, y = y2 + 2, w = g.w, h = 15,
               text = g.label, color = C.label, align = 0x04}

    local v = lvgl.label{x = g.x, y = y2 + 18, w = g.w, h = 32,
               text = g.value, color = g.color, align = 0x04}
    lvgl.setFont(v, F.b32)

    if g.unit and #g.unit > 0 then
      lvgl.label{x = g.x, y = y2 + h2 - 16, w = g.w, h = 14,
                 text = g.unit, color = C.label, align = 0x04}
    end
  end

  --[[==========================================================
    Legend bar
  ==========================================================]]
  lvgl.rectangle{x = 0, y = 260, w = 480, h = 1,
                 color = C.border, filled = true}
  lvgl.label{x = 0, y = 262, w = 480, h = 10,
    text = "DSEG7: Bold64  Bold48  Bold32  |  Regular: 48  32  |  TX16S  480×272",
    color = C.dim, align = 0x04}

  built = true
end

------------------------------
-- Script entry point
------------------------------
local fontErr = false
local function run()
  if not F.b64 then
    if not fontErr then
      lvgl.message{title = "HELI fonts unavailable",
        message = "Enable HELI in CMake and rebuild firmware"}
      fontErr = true
    end
    return 0
  end
  if not built then buildUI() end
  updateSim()
  return 0
end

return {run = run}
