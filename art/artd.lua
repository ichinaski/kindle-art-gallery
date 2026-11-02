#!/usr/bin/env lua
--[[
Art gallery for the Kindle PaperWhite 4, fully offline. Run by gallery.sh, which
pauses the Kindle UI before and always resumes it after, so exiting is just
returning from main().

  * the artwork fills the screen; it changes every INTERVAL seconds
  * swipe left / right: next / previous artwork
  * tap anywhere: bottom bar with title, artist, date, collection, battery, the
    refresh interval, Colecciones and Salir; tap above the bar to close it
  * Colecciones: one checkbox per collection (art movement); only ticked ones show.
    The works play in a shuffled order that goes through all before repeating.
  * failsafe: hold two fingers on the screen for 2 s to exit from any screen
  * power button: opens the bar; with the bar open, closes it and sleeps
  * frontlight: off before every sleep, so automatic changes happen in the dark;
    back to the starting level only when someone interacts (power button, touch)
  * sleep (SLEEP=1): after AWAKE seconds without touches the Kindle suspends until
    the next artwork change; the power button wakes it. Touch cannot wake it.
    A file named stay-awake in the art folder keeps it awake (development).

Input comes from bin/evtap, which grabs the touchscreen (so the paused UI never
sees our taps) and adds a heartbeat record, so one loop handles touches and timers.

Runs from a copy in RAM (ART_RUN, made by start-art.sh), so a USB connection to a
computer, which takes /mnt/us away, cannot pull files from under it. /mnt/us is only
touched to read the next image and to save state; both fail softly while it is away.

Desktop test: ART_SIM=1 with ART_DIR, ART_FBINK and ART_EVTAP pointing at fakes.
--]]

-- ---------------------------------------------------------------- constants
local DIR = os.getenv("ART_DIR") or "/mnt/us/art"
local FBINK = os.getenv("ART_FBINK") or "/mnt/us/libkh/bin/fbink"
local RUN = os.getenv("ART_RUN") or DIR -- program files (RAM copy on the Kindle)
local EVTAP = os.getenv("ART_EVTAP") or (RUN .. "/bin/evtap")
local SIM = os.getenv("ART_SIM") == "1"
local FONT_R = RUN .. "/fonts/AtkinsonHyperlegible-Regular.ttf"
local FONT_B = RUN .. "/fonts/AtkinsonHyperlegible-Bold.ttf"
local CONTENT = DIR .. "/content"      -- catalog.tsv, collections.tsv, images/<collection>/
local IMAGES = DIR .. "/images"        -- older layout: images/ + manifest.tsv
local MANIFEST = DIR .. "/manifest.tsv"
local CONF = DIR .. "/config"
local CAL = DIR .. "/calibration"
local STATE = DIR .. "/state"
local LOG = os.getenv("ART_LOG") or (SIM and DIR .. "/artd.log" or "/tmp/artd.log")
local TOUCH_DEV = "/dev/input/event2"
local POWER_DEVS = { "/dev/input/event0", "/dev/input/event1" }
local RTC = "/dev/rtc0"
local RTC_WAKEUP = "/sys/class/rtc/rtc0/device/power/wakeup"
local FB_ROTATE = os.getenv("ART_FB_ROTATE") or "/sys/class/graphics/fb0/rotate"

local W, H = 1448, 1072 -- logical screen, landscape

local EV_KEY, EV_ABS = 1, 3
local ABS_X, ABS_Y, ABS_PRESSURE = 0x00, 0x01, 0x18
local ABS_MT_SLOT, ABS_MT_POSITION_X, ABS_MT_POSITION_Y = 0x2f, 0x35, 0x36
local ABS_MT_TRACKING_ID, ABS_MT_PRESSURE = 0x39, 0x3a
local BTN_TOUCH, KEY_POWER = 330, 116
local HEARTBEAT = 0xFFFF

local INTERVALS = {
  { label = "1 minuto", short = "1 min", secs = 60 },
  { label = "1 hora",   short = "1 h",   secs = 3600 },
  { label = "3 horas",  short = "3 h",   secs = 10800 },
  { label = "6 horas",  short = "6 h",   secs = 21600 },
  { label = "24 horas", short = "24 h",  secs = 86400 },
}

local BAR_CLOSE_AFTER = 60   -- seconds without touches before the bar hides itself
local EXIT_HOLD = 2          -- two-finger hold that exits, in seconds
local BATT_LOW = 15          -- % at or below which a badge shows over the painting
local BATT_EMPTY = 5         -- % at or below which a charge screen replaces it

-- ---------------------------------------------------------------- utilities
local function logf(msg)
  local fh = io.open(LOG, "a")
  if fh then
    fh:write(os.date("%Y-%m-%d %H:%M:%S") .. " " .. msg .. "\n")
    fh:close()
  end
end

local function read_file(path)
  local fh = io.open(path, "r")
  if not fh then return nil end
  local s = fh:read("*a")
  fh:close()
  return s
end

local function write_file(path, s)
  local fh = io.open(path, "w")
  if not fh then return false end
  fh:write(s)
  fh:close()
  return true
end

-- In the desktop simulation, time advances 0.25 s per heartbeat record.
local sim_clock = 0

-- seconds since boot, with sub-second precision (for gestures)
local function now()
  if SIM then return sim_clock end
  local s = read_file("/proc/uptime")
  return tonumber(s and s:match("([%d%.]+)")) or os.time()
end

-- wall clock seconds (for the refresh interval)
local function wall()
  if SIM then return sim_clock end
  return os.time()
end

local function q(s)
  return "'" .. tostring(s):gsub("'", "'\\''") .. "'"
end

local function run(cmd)
  os.execute(cmd .. " >>" .. LOG .. " 2>&1")
end

local function capture(cmd)
  if not cmd:find("2>", 1, true) then cmd = cmd .. " 2>/dev/null" end
  local fh = io.popen(cmd)
  if not fh then return "" end
  local out = fh:read("*a") or ""
  fh:close()
  return out
end

local function int(v) return math.floor(v + 0.5) end

-- cut a UTF-8 string to n characters, so it fits on one line of the bar
local function shorten(s, n)
  s = s or ""
  local count, cut = 0, nil
  for pos in s:gmatch("()[^\128-\191]") do
    count = count + 1
    if count == n then cut = pos end
  end
  if count <= n then return s end
  return (s:sub(1, cut - 1):gsub("%s+$", "")) .. "..."
end

-- Font advance widths (art/widths.lua, from tools/fontwidths.py), to measure text.
-- Next to the running copy on the Kindle, next to this script in the simulator.
local WIDTHS
for _, d in ipairs({ RUN, (arg and arg[0] or ""):match("^(.*)/") or "." }) do
  local ok, t = pcall(dofile, d .. "/widths.lua")
  if ok and type(t) == "table" then WIDTHS = t; break end
end

-- width in pixels of s at size px (unknown characters count as an average 0.6 em)
local function text_width(s, px, bold)
  local t = WIDTHS and (bold and WIDTHS.bold or WIDTHS.regular)
  local units = 0
  for ch in (s or ""):gmatch("[%z\1-\127\194-\244][\128-\191]*") do
    local c = ch:byte(1)
    if #ch == 2 then c = (c % 32) * 64 + ch:byte(2) % 64
    elseif #ch == 3 then c = (c % 16) * 4096 + (ch:byte(2) % 64) * 64 + ch:byte(3) % 64
    elseif #ch == 4 then c = 0 end
    units = units + (t and t[c] or 600)
  end
  return units * px / 1000
end

-- the largest size from max down to min at which s fits in w pixels (5% margin for
-- the renderer's hinting and kerning); at min, s is cut until it fits
local function fit(s, max, min, w, bold)
  s = s or ""
  for px = max, min, -1 do
    if text_width(s, px, bold) * 1.05 <= w then return s, px end
  end
  local n = select(2, s:gsub("[^\128-\191]", ""))
  while n > 1 and text_width(shorten(s, n), min, bold) * 1.05 > w do n = n - 1 end
  return shorten(s, n), min
end

-- ---------------------------------------------------------------- config
local conf = { interval = 3600, rot = 0, sleep = 1, awake = 30, wifi = 0, off = {} }

local function load_conf()
  local s = read_file(CONF) or ""
  conf.interval = tonumber(s:match("INTERVAL=(%d+)")) or conf.interval
  conf.rot = tonumber(s:match("ROT=(%d+)")) or conf.rot
  conf.sleep = tonumber(s:match("SLEEP=(%d+)")) or conf.sleep
  conf.awake = tonumber(s:match("AWAKE=(%d+)")) or conf.awake
  conf.wifi = tonumber(s:match("WIFI=(%d+)")) or conf.wifi
  conf.off = {}
  for id in (s:match("OFF=([^\n]*)") or ""):gmatch("[^,%s]+") do conf.off[id] = true end
  if conf.awake < 5 then conf.awake = 5 end
  local r = read_file(DIR .. "/rotation")
  if r and r:match("%d") then conf.rot = tonumber(r:match("(%d)")) end
end

local function save_conf()
  local off = {}
  for id in pairs(conf.off) do off[#off + 1] = id end
  table.sort(off)
  -- keep lines for other programs (REPO= for artsync.sh) as they are
  local mine = { INTERVAL = true, ROT = true, SLEEP = true, AWAKE = true, WIFI = true, OFF = true }
  local other = {}
  for line in (read_file(CONF) or ""):gmatch("[^\n]+") do
    local key = line:match("^(%w+)=")
    if not (key and mine[key]) then other[#other + 1] = line .. "\n" end
  end
  write_file(CONF, string.format("INTERVAL=%d\nROT=%d\nSLEEP=%d\nAWAKE=%d\nWIFI=%d\nOFF=%s\n",
    conf.interval, conf.rot, conf.sleep, conf.awake, conf.wifi, table.concat(off, ",")) ..
    table.concat(other))
end

-- ---------------------------------------------------------------- drawing
-- Draw calls are queued and run in one shell when the screen is refreshed. They
-- skip the refresh (-b); refresh() then updates the screen once.
local queue = {}
local last_draw = -1000 -- now() after the last screen update

local function fb(args)
  table.insert(queue, FBINK .. " -q " .. args)
end

local function flush()
  if #queue == 0 then return end
  local t0 = now()
  os.execute("{ " .. table.concat(queue, "; ") .. "; } >/dev/null 2>&1")
  last_draw = now()
  logf(string.format("draw: %d fbink calls in %.2fs", #queue, last_draw - t0))
  queue = {}
end

local function fill(x, y, w, h, color)
  fb(string.format("-b -B %s -k top=%d,left=%d,width=%d,height=%d", color, y, x, w, h))
end

local function refresh(x, y, w, h, flash)
  fb(string.format("%s-s top=%d,left=%d,width=%d,height=%d", flash and "-f " or "", y, x, w, h))
  flush()
end

-- text in the box x,y,w,h: vertically centred, left aligned or centred
local function text(s, px, x, y, w, h, o)
  o = o or {}
  local top = y + math.max(0, int((h - px * 1.3) / 2))
  local args = string.format(
    "-b -t regular=%s,bold=%s,px=%d,top=%d,bottom=%d,left=%d,right=%d,style=%s",
    FONT_R, FONT_B, px, top, math.max(0, H - (y + h)), x, math.max(0, W - (x + w)),
    o.bold and "BOLD" or "REGULAR")
  if o.center then args = args .. " -m" end
  if o.invert then args = args .. " -h" end
  fb(args .. " " .. q(s))
end

local function show_image(path)
  fb("-f -g file=" .. q(path))
  flush()
end

local function message(s)
  fill(0, 0, W, H, "WHITE")
  text(s, 44, 0, int(H / 2) - 60, W, 120, { bold = true, center = true })
  refresh(0, 0, W, H, true)
end

-- ---------------------------------------------------------------- battery
local batt_cache, batt_time = nil, -1000

local function battery(fresh)
  if SIM then return tonumber(os.getenv("ART_BATTERY") or "77"), os.getenv("ART_CHARGING") == "1" end
  if not fresh and batt_cache and now() - batt_time < 60 then return batt_cache[1], batt_cache[2] end
  local pct = tonumber(capture("gasgauge-info -c"):match("(%d+)"))
    or tonumber(capture("lipc-get-prop com.lab126.powerd battLevel"):match("(%d+)"))
  local charging = capture("lipc-get-prop com.lab126.powerd isCharging"):match("^%s*1") ~= nil
  batt_cache, batt_time = { pct, charging }, now()
  return pct, charging
end

-- ---------------------------------------------------------------- artwork
-- content/catalog.tsv (built by content/build.py): id, collection, file, sha256,
-- title, artist, date; files live in content/images/. content/collections.tsv: id,
-- name, order. Older installs have manifest.tsv + images/ instead: one collection.
local catalog = {}      -- every work: { id, coll, path, title, artist, date }
local collections = {}  -- shown collections, in order: { id, name, count }
local playlist = {}     -- shuffled indices into catalog, ticked collections only
local pos = 1           -- position in playlist
local last_change = 0   -- wall() of the last automatic or manual change

local function fields(line)
  local t = {}
  for f in (line .. "\t"):gmatch("([^\t]*)\t") do t[#t + 1] = f end
  return t
end

local function load_catalog()
  catalog, collections = {}, {}
  local s = read_file(CONTENT .. "/catalog.tsv")
  local names, order = {}, {}
  if s then
    for line in s:gmatch("[^\n]+") do
      local f = fields(line)
      if not line:match("^#") and f[1] ~= "" and f[3] then
        table.insert(catalog, { id = f[1], coll = f[2], path = CONTENT .. "/images/" .. f[3],
                                title = f[5] or "", artist = f[6] or "", date = f[7] or "" })
      end
    end
    for line in (read_file(CONTENT .. "/collections.tsv") or ""):gmatch("[^\n]+") do
      local f = fields(line)
      if not line:match("^#") and f[1] ~= "" then
        names[f[1]], order[f[1]] = f[2] or f[1], tonumber(f[3]) or 1000
      end
    end
  else
    for line in (read_file(MANIFEST) or ""):gmatch("[^\n]+") do
      local f = fields(line)
      if f[1] ~= "" then
        table.insert(catalog, { id = f[1], coll = "galeria", path = IMAGES .. "/" .. f[1],
                                title = f[2] or "", artist = f[3] or "", date = f[4] or "" })
      end
    end
    names.galeria = "Galería"
  end
  local count = {}
  for _, w in ipairs(catalog) do count[w.coll] = (count[w.coll] or 0) + 1 end
  for id, n in pairs(count) do
    table.insert(collections, { id = id, name = names[id] or id, count = n, order = order[id] or 1000 })
  end
  table.sort(collections, function(x, y)
    if x.order ~= y.order then return x.order < y.order end
    return x.id < y.id
  end)
end

local function enabled_count()
  local n = 0
  for _, c in ipairs(collections) do if not conf.off[c.id] then n = n + 1 end end
  return n
end

local function current() return catalog[playlist[pos] or 0] end

local function save_state()
  local ids = {}
  for i, k in ipairs(playlist) do ids[i] = catalog[k].id end
  write_file(STATE, "pos=" .. pos .. "\norder=" .. table.concat(ids, ",") .. "\n")
end

local function shuffle(t)
  if os.getenv("ART_NOSHUFFLE") == "1" then return end -- desktop tests: catalogue order
  for i = #t, 2, -1 do
    local j = math.random(i)
    t[i], t[j] = t[j], t[i]
  end
end

-- New shuffled order over the ticked collections; `first` (an id) goes first.
local function build_playlist(first)
  playlist = {}
  for k, w in ipairs(catalog) do
    if not conf.off[w.coll] then playlist[#playlist + 1] = k end
  end
  shuffle(playlist)
  for i, k in ipairs(playlist) do
    if catalog[k].id == first then
      playlist[1], playlist[i] = playlist[i], playlist[1]
      break
    end
  end
  pos = 1
  save_state()
  logf(string.format("playlist: %d works from %d collections", #playlist, enabled_count()))
end

-- Resume the saved order if it still matches the ticked collections exactly.
local function load_playlist()
  local s = read_file(STATE) or ""
  local by_id = {}
  for k, w in ipairs(catalog) do by_id[w.id] = k end
  local saved, wanted = {}, 0
  for _, w in ipairs(catalog) do if not conf.off[w.coll] then wanted = wanted + 1 end end
  for id in (s:match("order=([^\n]*)") or ""):gmatch("[^,]+") do
    local k = by_id[id]
    if k and not conf.off[catalog[k].coll] then saved[#saved + 1] = k end
  end
  if #saved == wanted and wanted > 0 then
    playlist = saved
    pos = tonumber(s:match("pos=(%d+)")) or 1
    if pos < 1 or pos > #playlist then pos = 1 end
  else
    build_playlist(nil)
  end
end

local function show_artwork()
  local it = current()
  if not it then return end
  local fh = io.open(it.path, "rb")
  if not fh then
    -- /mnt/us is away (USB drive mode) or the file is missing: keep the screen
    logf("cannot read " .. it.path .. ", keeping the current picture")
    last_change = wall()
    return
  end
  fh:close()
  local pct, charging = battery(true) -- fresh: the cache may predate a long sleep
  local low = pct and not charging and pct <= BATT_LOW
  if low and pct <= BATT_EMPTY then
    -- nearly empty: ask for a charge instead of dying on a normal-looking painting
    logf(string.format("battery %d%%: showing the charge screen", pct))
    fill(0, 0, W, H, "WHITE")
    text("Batería casi agotada", 64, 0, int(H / 2) - 150, W, 110, { bold = true, center = true })
    text("Por favor, carga el Kindle", 48, 0, int(H / 2) - 10, W, 90, { center = true })
    text(string.format("%d%%", pct), 40, 0, int(H / 2) + 110, W, 80, { center = true })
    refresh(0, 0, W, H, true)
    last_change = wall()
    return
  end
  logf(string.format("showing %d/%d: %s - %s (%s)", pos, #playlist, it.title, it.artist, it.coll))
  show_image(it.path)
  if low then
    -- small badge in the bottom-right corner, over the painting
    local label = string.format("Batería baja · %d%%", pct)
    local bw = int(text_width(label, 30, true) * 1.05) + 48
    local bx, by, bh = W - bw - 24, H - 24 - 64, 64
    fill(bx - 3, by - 3, bw + 6, bh + 6, "WHITE")
    fill(bx, by, bw, bh, "BLACK")
    text(label, 30, bx + 6, by + 4, bw - 12, bh - 8, { bold = true, center = true, invert = true })
    refresh(bx - 3, by - 3, bw + 6, bh + 6)
    logf(string.format("battery %d%%: low-battery badge shown", pct))
  end
  last_change = wall()
end

local function step(delta)
  if #playlist == 0 then return end
  pos = pos + delta
  if pos > #playlist then
    -- every work shown once: new order, not starting with the one just shown
    local last = current() and current().id
    build_playlist(nil)
    if #playlist > 1 and catalog[playlist[1]].id == last then
      playlist[1], playlist[2] = playlist[2], playlist[1]
      save_state()
    end
  elseif pos < 1 then
    pos = #playlist
  end
  save_state()
  show_artwork()
end

local function collection_name(id)
  for _, c in ipairs(collections) do if c.id == id then return c.name end end
  return id
end

-- ---------------------------------------------------------------- the bar
-- An information card: title, artist and date, collection and battery. The only
-- controls are previous, next and Ajustes; everything rarely used is one level down.
local BAR_H = 300
local BAR_Y = H - BAR_H
local PAD = 16

-- buttons in the bottom row of the bar (x, w); between them, collection and battery
local BTN_Y, BTN_H = BAR_Y + 186, 96
local BUTTONS = {
  { id = "prev",     x = 24,          w = 120, label = "«" },
  { id = "next",     x = 160,         w = 120, label = "»" },
  { id = "settings", x = W - 24 - 300, w = 300, label = "Ajustes" },
}
local META_X = 160 + 120 + 24
local META_W = W - 24 - 300 - 24 - META_X

-- an outlined button, or a black one (primary) with white text
local function draw_box(x, y, w, h, label, px, primary)
  fill(x, y, w, h, "BLACK")
  if not primary then fill(x + 3, y + 3, w - 6, h - 6, "WHITE") end
  local s, size = fit(label, px, math.max(24, px - 10), w - 24, true)
  text(s, size, x + 6, y + 6, w - 12, h - 12, { bold = true, center = true, invert = primary })
end

local function hit(b, x, y)
  return x >= b.x - PAD and x <= b.x + b.w + PAD and y >= b.y - PAD and y <= b.y + b.h + PAD
end

local function draw_bar()
  local it = current() or { title = "", artist = "", date = "" }
  fill(0, BAR_Y, W, BAR_H, "BLACK")
  fill(0, BAR_Y + 3, W, BAR_H - 3, "WHITE")

  -- whole title, artist and date, across the full width: shrink to fit, never cut
  local s, px = fit(it.title, 50, 34, W - 64, true)
  text(s, px, 32, BAR_Y + 16, W - 64, 76, { bold = true })
  local sub = it.artist or ""
  if it.date and it.date ~= "" then sub = sub .. ", " .. it.date end
  s, px = fit(sub, 36, 26, W - 64)
  text(s, px, 32, BAR_Y + 96, W - 64, 62)

  -- collection, position and battery; if too long, the collection name gives way
  local pct, charging = battery()
  local batt = pct and string.format("Batería %d%%", pct) or "Batería ?"
  if charging then batt = batt .. " (cargando)" end
  local tail = string.format(" · %d/%d   ·   %s", pos, #playlist, batt)
  local name = collection_name(it.coll)
  s, px = fit(name .. tail, 32, 24, META_W)
  if s ~= name .. tail then
    s = fit(name, 24, 24, META_W - text_width(tail, 24) * 1.05) .. tail
  end
  text(s, px, META_X, BTN_Y, META_W, BTN_H, { center = true })

  for _, b in ipairs(BUTTONS) do draw_box(b.x, BTN_Y, b.w, BTN_H, b.label, 38, false) end
  refresh(0, BAR_Y, W, BAR_H)
  logf(string.format("bar shown (battery %s%s)", tostring(pct), charging and ", charging" or ""))
end

local function button_at(x, y)
  for _, b in ipairs(BUTTONS) do
    if hit({ x = b.x, y = BTN_Y, w = b.w, h = BTN_H }, x, y) then return b end
  end
  return nil
end

-- ---------------------------------------------------------------- Ajustes
-- Collections (two columns of checkboxes), the change interval, Salir and Listo.
local CL_TOP, CL_ROW, CL_W = 150, 80, 640
local CL_X = { 60, 760 }
local SEG_X, SEG_Y, SEG_W, SEG_H, SEG_GAP = 400, 742, 150, 80, 14
local EXIT = { x = 60, y = 930, w = 480, h = 100 }
local DONE = { x = W - 60 - 400, y = 930, w = 400, h = 100 }

local function coll_box(i)
  local c = collections[i]
  local x = CL_X[(i - 1) % 2 + 1]
  local y = CL_TOP + math.floor((i - 1) / 2) * CL_ROW
  return c, x, y
end

local function draw_coll_row(i)
  local c, x, y = coll_box(i)
  fill(x, y, CL_W, CL_ROW - 4, "WHITE")
  fill(x, y + 12, 56, 56, "BLACK")
  fill(x + 5, y + 17, 46, 46, "WHITE")
  if not conf.off[c.id] then fill(x + 13, y + 25, 30, 30, "BLACK") end
  -- measured at the bold width either way, so ticking a row never changes its size
  local label, px = fit(c.name .. "  (" .. c.count .. ")", 36, 28, CL_W - 80, true)
  text(label, px, x + 80, y, CL_W - 80, 80, { bold = not conf.off[c.id] })
end

local function seg_box(k)
  return { x = SEG_X + (k - 1) * (SEG_W + SEG_GAP), y = SEG_Y, w = SEG_W, h = SEG_H }
end

local function draw_interval()
  fill(0, SEG_Y - 4, W, SEG_H + 8, "WHITE")
  text("Cambiar cada", 36, 60, SEG_Y, SEG_X - 80, SEG_H, { bold = true })
  for k, it in ipairs(INTERVALS) do
    local b = seg_box(k)
    draw_box(b.x, b.y, b.w, b.h, it.short, 34, it.secs == conf.interval)
  end
end

local function draw_settings()
  fill(0, 0, W, H, "WHITE")
  text("Ajustes", 52, 0, 20, W, 80, { bold = true, center = true })
  text("Colecciones", 36, 60, 96, 600, 50, { bold = true })
  for i = 1, #collections do draw_coll_row(i) end
  draw_interval()
  draw_box(EXIT.x, EXIT.y, EXIT.w, EXIT.h, "Salir de la galería", 34, false)
  draw_box(DONE.x, DONE.y, DONE.w, DONE.h, "Listo", 44, true)
  refresh(0, 0, W, H, true)
  logf("settings shown")
end

-- what a tap on Ajustes hits: "done", "exit", { interval = secs }, a collection index
local function settings_hit(x, y)
  if hit(DONE, x, y) then return "done" end
  if hit(EXIT, x, y) then return "exit" end
  for k, it in ipairs(INTERVALS) do
    local b = seg_box(k)
    if x >= b.x - SEG_GAP / 2 and x <= b.x + b.w + SEG_GAP / 2 and y >= b.y - PAD
        and y <= b.y + b.h + PAD then
      return { interval = it.secs }
    end
  end
  for i = 1, #collections do
    local _, cx, cy = coll_box(i)
    if x >= cx - PAD and x <= cx + CL_W + PAD and y >= cy and y < cy + CL_ROW then return i end
  end
  return nil
end

-- ---------------------------------------------------------------- exit confirmation
local STAY = { x = 214, y = 690, w = 500, h = 120 }
local LEAVE = { x = 734, y = 690, w = 500, h = 120 }

local function draw_confirm()
  fill(0, 0, W, H, "WHITE")
  text("¿Salir de la galería?", 60, 0, 250, W, 110, { bold = true, center = true })
  text("Volverás a la biblioteca del Kindle.", 38, 0, 420, W, 60, { center = true })
  text("Para volver a la galería, abre «1. Galería de arte».", 38, 0, 490, W, 60, { center = true })
  draw_box(STAY.x, STAY.y, STAY.w, STAY.h, "No, seguir aquí", 40, true)
  draw_box(LEAVE.x, LEAVE.y, LEAVE.w, LEAVE.h, "Sí, salir", 40, false)
  refresh(0, 0, W, H, true)
  logf("exit confirmation shown")
end

-- the screens' helpers in one table: main() is near Lua 5.1's limit of 60 upvalues
local UI = { hit = hit, draw_settings = draw_settings, draw_confirm = draw_confirm,
  settings_hit = settings_hit, draw_interval = draw_interval, coll_box = coll_box,
  draw_coll_row = draw_coll_row, STAY = STAY, LEAVE = LEAVE, SEG_Y = SEG_Y,
  SEG_H = SEG_H, CL_W = CL_W, CL_ROW = CL_ROW }

-- ---------------------------------------------------------------- touch mapping
-- The touchscreen reports the panel's own portrait coordinates (0..1072 x 0..1448),
-- already calibrated by the controller, so landscape is a fixed rotation that
-- depends only on the framebuffer rotation in use (measured on the PW4: within 18 px
-- of a fitted map). A file named `calibration` with an affine map (a..f, as written
-- by older versions) overrides it, should another device need one.
local cal = nil

local function load_cal()
  local s = read_file(CAL)
  if not s then return nil end
  local c = {}
  for _, k in ipairs({ "a", "b", "c", "d", "e", "f" }) do
    c[k] = tonumber(s:match("\n" .. k .. "=([%-%d%.e]+)") or s:match("^" .. k .. "=([%-%d%.e]+)"))
    if not c[k] then return nil end
  end
  return c
end

local function map_point(rx, ry)
  if cal then
    return int(cal.a * rx + cal.b * ry + cal.c), int(cal.d * rx + cal.e * ry + cal.f)
  end
  if conf.rot == 2 then return (W - 1) - ry, rx end -- the other landscape
  return ry, (H - 1) - rx                            -- ROT=0, the one this PW4 uses
end

-- ---------------------------------------------------------------- touch tracking
-- Turns raw events into finished gestures {sx, sy, x, y, dur, fingers} in raw
-- coordinates. A gesture ends when every finger has lifted. If the screen has never
-- reported a lift, a pause in events ends it instead.
--
-- The kernel only sends a coordinate when it changes, per slot, even across
-- touches: a new touch at the same X as the last one sends no X at all. So the
-- positions persist between touches, and the start point is taken when the first
-- report of a touch is complete (SYN_REPORT), not from the first coordinate seen.
local EV_SYN = 0
local touch = { active = false, slot = 0, slots = {}, n = 0, lift_seen = false, last = 0,
                pos = {} }

local function slot_pos(slot)
  local p = touch.pos[slot]
  if not p then p = {}; touch.pos[slot] = p end
  return p
end

local function touch_begin()
  touch.active, touch.t0, touch.fingers = true, now(), 1
  touch.primary, touch.need_start = touch.slot, true
  touch.sx, touch.sy = nil, nil
end

local function touch_end()
  touch.active, touch.slots, touch.n = false, {}, 0
  local p = slot_pos(touch.primary or 0)
  if not p.x or not p.y then return nil end
  return { sx = touch.sx or p.x, sy = touch.sy or p.y, x = p.x, y = p.y,
           dur = now() - touch.t0, fingers = touch.fingers }
end

local function touch_feed(type_, code, value)
  if type_ == EV_SYN then
    if code == 0 and touch.active and touch.need_start then
      local p = slot_pos(touch.primary)
      touch.sx, touch.sy, touch.need_start = p.x, p.y, false
    end
  elseif type_ == EV_ABS then
    touch.last = now()
    if code == ABS_MT_SLOT then
      touch.slot = value
    elseif code == ABS_MT_TRACKING_ID then
      if value >= 0 then
        if not touch.active then touch_begin() end
        if not touch.slots[touch.slot] then
          touch.slots[touch.slot] = true
          touch.n = touch.n + 1
        end
        if touch.n > touch.fingers then touch.fingers = touch.n end
      else
        touch.lift_seen = true
        if touch.slots[touch.slot] then
          touch.slots[touch.slot] = nil
          touch.n = touch.n - 1
        end
        if touch.active and touch.n <= 0 then return touch_end() end
      end
    elseif code == ABS_MT_POSITION_X then
      slot_pos(touch.slot).x = value
    elseif code == ABS_MT_POSITION_Y then
      slot_pos(touch.slot).y = value
    elseif code == ABS_X or code == ABS_Y then
      -- single-touch screens: only these, no MT slots
      if not touch.active then touch_begin() end
      if code == ABS_X then slot_pos(0).x = value else slot_pos(0).y = value end
    elseif (code == ABS_PRESSURE or code == ABS_MT_PRESSURE) and value > 0 then
      if not touch.active then touch_begin() end
    end
  elseif type_ == EV_KEY and code == BTN_TOUCH then
    if value == 1 and not touch.active then
      touch_begin()
    elseif value == 0 and touch.active then
      touch.lift_seen = true
      return touch_end()
    end
  end
  return nil
end

-- called on every heartbeat: ends a gesture whose lift never arrived
local function touch_tick()
  if not touch.active then return nil end
  local limit = touch.lift_seen and 5 or 0.6
  if now() - touch.last > limit then return touch_end() end
  return nil
end

-- ---------------------------------------------------------------- input
local input = nil

local function open_input()
  local devs = "-g " .. TOUCH_DEV
  if not SIM then
    for _, d in ipairs(POWER_DEVS) do
      local fh = io.open(d, "rb")
      -- grabbed: the gallery owns the power button, powerd never sees it
      if fh then fh:close(); devs = devs .. " -g " .. d end
    end
  end
  input = io.popen(EVTAP .. " -t 250 " .. devs .. " 2>>" .. LOG)
  return input
end

local last_ev_sec = 0 -- kernel time (wall clock seconds) of the latest touch record

local function parse_event(buf)
  local b = { string.byte(buf, 1, 16) }
  local type_ = b[9] + b[10] * 256
  if type_ ~= HEARTBEAT then last_ev_sec = b[1] + b[2] * 256 + b[3] * 65536 + b[4] * 16777216 end
  local code = b[11] + b[12] * 256
  local value = b[13] + b[14] * 256 + b[15] * 65536 + b[16] * 16777216
  if value >= 2147483648 then value = value - 4294967296 end
  return type_, code, value
end

-- next record from evtap; nil when the stream ends
local function next_event()
  local buf = input:read(16)
  if not buf or #buf < 16 then return nil end
  local type_, code, value = parse_event(buf)
  if SIM and type_ == HEARTBEAT then sim_clock = sim_clock + 0.25 end
  return type_, code, value
end

-- ---------------------------------------------------------------- rotation
local function fb_geometry()
  local w, h = capture(FBINK .. " -v 2>&1"):match("Variable fb info: (%d+)x(%d+)")
  return tonumber(w), tonumber(h)
end

-- try the saved rotation first, keep the first one that makes the screen landscape
local function pick_rotation()
  for _, v in ipairs({ conf.rot, 0, 1, 2, 3 }) do
    write_file(FB_ROTATE, v .. "\n")
    local w, h = fb_geometry()
    logf(string.format("rotation %d -> %sx%s", v, tostring(w), tostring(h)))
    if w and h and w > h then
      if v ~= conf.rot then conf.rot = v; save_conf() end
      write_file(DIR .. "/rotation", v .. "\n")
      return true
    end
  end
  write_file(FB_ROTATE, conf.rot .. "\n")
  return false
end

-- ---------------------------------------------------------------- frontlight
-- The kernel turns the light off during suspend and restores the previous level on
-- resume, so it must be 0 *before* sleeping or every automatic change lights up.
-- `level` is the user's level when the gallery started (0 if they had it off).
local light = { dir = nil, level = 0, current = nil }

local function light_init()
  light.dir = os.getenv("ART_BACKLIGHT")
  if not light.dir and not SIM then
    local name = capture("ls /sys/class/backlight"):match("([^\n]+)")
    if name then light.dir = "/sys/class/backlight/" .. name end
  end
  if not light.dir then
    logf("no frontlight found")
    return
  end
  light.level = tonumber((read_file(light.dir .. "/brightness") or ""):match("(%d+)")) or 0
  light.current = light.level
  logf(string.format("frontlight %s, level %d of %s", light.dir, light.level,
    tostring((read_file(light.dir .. "/max_brightness") or "?"):match("(%d+)"))))
end

local function light_set(on)
  if not light.dir then return end
  local v = on and light.level or 0
  if light.current == v then return end
  write_file(light.dir .. "/brightness", v .. "\n")
  light.current = v
  logf("frontlight " .. (on and "on" or "off") .. " (" .. v .. ")")
end

-- ---------------------------------------------------------------- sleep
-- Suspend to RAM until the clock alarm or the power button wakes the Kindle.
-- Returns the seconds actually slept. The e-ink screen keeps the picture.
-- remaining charge in mAh, for measuring the sleep current
local function charge_mah()
  if SIM then return nil end
  local v = tonumber(capture("gasgauge-info -m"):match("(%d+)"))
  return v and v / 1000 -- reported in µAh
end

local function suspend(secs)
  secs = math.floor(secs)
  light_set(false)
  local before = charge_mah()
  logf(string.format("sleeping for up to %ds (charge %s mAh)", secs, tostring(before)))
  local t0 = wall()
  if SIM then
    sim_clock = sim_clock + secs
  else
    write_file(RTC_WAKEUP, "enabled\n")
    os.execute(string.format("sync; rtcwake -d %s -m mem -s %d >/dev/null 2>&1", RTC, secs))
  end
  local slept = wall() - t0
  logf(string.format("awake after %ds (charge %s mAh)", slept, tostring(charge_mah())))
  return slept
end

local function stay_awake()
  return conf.sleep ~= 1 or io.open(DIR .. "/stay-awake", "r") ~= nil
end

-- ---------------------------------------------------------------- main loop
local function main()
  os.remove(LOG)
  load_conf()
  math.randomseed(os.time())
  load_catalog()
  logf(string.format("artd starting: %d artworks in %d collections, interval %ds, sleep %d after %ds, wifi %d",
    #catalog, #collections, conf.interval, conf.sleep, conf.awake, conf.wifi))
  if #catalog == 0 then
    message("No hay imágenes en " .. CONTENT)
    os.execute("sleep 5")
    return "no artworks"
  end

  if not pick_rotation() then logf("WARNING: no rotation gave a landscape screen") end
  light_init()

  if not open_input() or not next_event() then
    message("No se puede leer la pantalla táctil")
    os.execute("sleep 5")
    return "no input (see evtap error above)"
  end

  cal = load_cal()
  if cal then logf("touch: using the calibration file") end

  if enabled_count() == 0 then conf.off = {} end -- never leave nothing to show
  load_playlist()
  show_artwork()
  if conf.wifi == 0 and not SIM then
    run("lipc-set-prop com.lab126.cmd wirelessEnable 0")
    logf("wifi off (WIFI=0)")
  end

  local bar_open, bar_since = false, 0
  -- screen: nil (the painting, maybe with the bar), "settings" or "confirm"
  local screen, colls_before = nil, nil
  local keepalive_at = now() + 300
  local last_activity, last_power = now(), -1000

  local function open_bar()
    bar_open, bar_since = true, now()
    draw_bar()
  end

  local function close_bar()
    bar_open = false
    show_artwork()
  end

  local function open_settings()
    bar_open, screen, bar_since = false, "settings", now()
    colls_before = {}
    for id in pairs(conf.off) do colls_before[id] = true end
    UI.draw_settings()
  end

  -- leave Ajustes (or the exit confirmation); if the collections changed, save them
  -- and reshuffle. The interval is saved as soon as it is picked.
  local function close_settings()
    screen = nil
    local changed = false
    for _, c in ipairs(collections) do
      if (conf.off[c.id] or false) ~= (colls_before[c.id] or false) then changed = true end
    end
    if changed then
      save_conf()
      local it = current()
      build_playlist(it and not conf.off[it.coll] and it.id or nil)
      local off = {}
      for id in pairs(conf.off) do off[#off + 1] = id end
      logf("collections off: " .. (#off > 0 and table.concat(off, ",") or "none"))
    end
    show_artwork()
  end

  -- called on every heartbeat: sleep when idle and the screen has settled
  local function maybe_sleep()
    local t = now()
    if touch.active or t - last_activity < conf.awake or t - last_draw < 3 then return end
    if stay_awake() then return end
    if screen then close_settings(); return end
    if bar_open then close_bar(); return end -- sleep on a later beat, once drawn
    local left = conf.interval - (wall() - last_change)
    if left <= 3 then return end -- the change is due: let the loop draw it first
    suspend(left)
    -- if nothing (no key) follows the wake-up, go back to sleep in a few seconds
    last_activity = now() - conf.awake + 4
  end

  while true do
    local type_, code, value = next_event()
    if not type_ then return "input stream ended" end
    local g

    if type_ == HEARTBEAT then
      g = touch_tick()
      local t = now()
      if touch.active and touch.fingers >= 2 and t - touch.t0 >= EXIT_HOLD then
        return "two-finger hold"
      end
      if screen then
        if t - bar_since > BAR_CLOSE_AFTER then close_settings() end
      elseif bar_open and t - bar_since > BAR_CLOSE_AFTER then
        close_bar()
      elseif not bar_open and wall() - last_change >= conf.interval then
        step(1)
      end
      maybe_sleep()
      if not SIM and t >= keepalive_at then
        keepalive_at = t + 300
        run("lipc-set-prop com.lab126.powerd preventScreenSaver 1")
      end
    elseif type_ == EV_KEY and code == KEY_POWER then
      -- act on release; both power devices may report the same press
      if value == 0 and now() - last_power > 0.7 then
        last_power = now()
        logf("power button (bar " .. (bar_open and "open" or "closed") .. ")")
        if screen then
          close_settings()
          last_activity = now()
        elseif bar_open then
          close_bar()
          last_activity = now() - conf.awake -- sleep as soon as the screen settles
        else
          light_set(true)
          open_bar()
          last_activity = now()
        end
      end
    else
      if type_ == EV_ABS then last_activity = now() end
      g = touch_feed(type_, code, value)
    end

    if g then
      light_set(true) -- someone is interacting
      local sx, sy = map_point(g.sx, g.sy)
      local x, y = map_point(g.x, g.y)
      local dx, dy = x - sx, y - sy
      logf(string.format("gesture: %d finger(s), %.2fs, %d,%d -> %d,%d (bar %s, handled %ds after the touch)",
        g.fingers, g.dur, sx, sy, x, y, bar_open and "open" or "closed",
        SIM and 0 or (os.time() - last_ev_sec)))
      if g.fingers >= 2 then
        if g.dur >= EXIT_HOLD then return "two-finger hold" end
      elseif screen == "confirm" then
        bar_since = now()
        if math.abs(dx) < 60 and math.abs(dy) < 60 then
          if UI.hit(UI.LEAVE, x, y) then
            logf("exit confirmed")
            return "exit button"
          elseif UI.hit(UI.STAY, x, y) then
            logf("exit cancelled")
            screen = "settings"
            UI.draw_settings()
          end
        end
      elseif screen == "settings" then
        bar_since = now()
        if math.abs(dx) < 60 and math.abs(dy) < 60 then
          local h = UI.settings_hit(x, y)
          if h == "done" then
            close_settings()
          elseif h == "exit" then
            screen = "confirm"
            UI.draw_confirm()
          elseif type(h) == "table" then
            if h.interval ~= conf.interval then
              conf.interval = h.interval
              save_conf()
              last_change = wall()
              logf("interval set to " .. conf.interval .. "s")
              UI.draw_interval()
              refresh(0, UI.SEG_Y - 4, W, UI.SEG_H + 8)
            end
          elseif h then
            local c = collections[h]
            if not conf.off[c.id] and enabled_count() <= 1 then
              logf("collection " .. c.id .. ": the last one stays on")
            else
              conf.off[c.id] = not conf.off[c.id] or nil
              logf("collection " .. c.id .. (conf.off[c.id] and " off" or " on"))
              local _, cx, cy = UI.coll_box(h)
              UI.draw_coll_row(h)
              refresh(cx, cy, UI.CL_W, UI.CL_ROW - 4)
            end
          end
        end
      elseif math.abs(dx) > 80 and math.abs(dx) > 1.5 * math.abs(dy) then
        step(dx < 0 and 1 or -1)
        if bar_open then draw_bar(); bar_since = now() end
      elseif math.abs(dx) < 60 and math.abs(dy) < 60 then
        if not bar_open then
          open_bar()
        elseif y < BAR_Y - PAD then
          close_bar()
        else
          bar_since = now()
          local b = button_at(x, y)
          if b then logf("button " .. b.id) end
          if b and b.id == "prev" then
            step(-1); draw_bar()
          elseif b and b.id == "next" then
            step(1); draw_bar()
          elseif b and b.id == "settings" then
            open_settings()
          end
        end
      end
    end
  end
end

local ok, why = pcall(main)
if not ok then logf("ERROR: " .. tostring(why)) end
logf("stopping: " .. tostring(why))
if ok and why ~= "no artworks" then
  pcall(message, "Volviendo al Kindle...")
end
if input then input:close() end
os.exit(ok and 0 or 1)
