#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# mib2image_gimp3
# MIB2STD boot image loader/exporter for GIMP 3.x
#
# Version: 1.1.3
#
# Copyright (C) 2003, 2005 Manish Singh <yosh@gimp.org>
# Copyright (C) 2021 John Tomatos
# Copyright (C) 2026 MrGame11
#
# GIMP is Copyright (C) The GIMP Development Team and contributors.
#
# Original Gimp-Python components:
#   Gimp-Python - allows the writing of GIMP plug-ins in Python.
#   Copyright (C) 2003, 2005 Manish Singh <yosh@gimp.org>
#
# Original MIB2STD GIMP 2.x / Python 2 plug-in:
#   Copyright (C) 2021 John Tomatos
#
# GIMP 3.x / Python 3 port and further development:
#   Copyright (C) 2026 MrGame11
#
# Project:
#   https://github.com/MrGame11/mib-std2-pq-zr-toolbox_mib2image_gimp3
#
# License:
#   GNU General Public License, version 3 or (at your option) any later version.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
#
# This project is an independent third-party plug-in and is not an official
# project of, or endorsed by, The GIMP Development Team.


"""
mib2image_gimp3
===============

MIB2STD boot image loader and exporter for GIMP 3.x.

Version: 1.1.3
Author / GIMP 3.x port: MrGame11 (2026)
Project: https://github.com/MrGame11/mib-std2-pq-zr-toolbox_mib2image_gimp3
License: GNU GPL v3 or later (GPL-3.0-or-later)

This plug-in is a GIMP 3.x / Python 3 port of the original GIMP 2.x /
Python 2 MIB2STD plug-in created by John Tomatos in 2021 (https://github.com/olli991/mib-std2-pq-zr-toolbox).

The core MIB2 image conversion functionality and conversion formulas of
the original plug-in have been retained while the GIMP integration has
been adapted for the GIMP 3.x plug-in API and Python 3.

The .mib files handled by this plug-in are PNG containers using 8-bit
grayscale and alpha pixel data. The grayscale byte contains the packed
chroma value, while the alpha byte contains the green/luma value used by
the original MIB2 conversion algorithm.

The plug-in supports:

- Loading MIB2STD boot images into GIMP as RGB images.
- Exporting GIMP images to the MIB2STD image format.
- Optional color-level limiting to reduce the resulting file size.
- Optional extraction of the 480 x 100 pixel label area from compatible
  800 x 480 pixel images.
- Preservation of the original MIB2 pixel conversion logic.

This is an independent third-party plug-in and is not an official GIMP
project or endorsed by The GIMP Development Team.
"""


__version__ = "1.1.3"
__author__ = "MrGame11"
__license__ = "GPL-3.0-or-later"
__url__ = "https://github.com/MrGame11/mib-std2-pq-zr-toolbox_mib2image_gimp3"

import math
import os
import re
import struct
import sys
import tempfile
import zlib
from datetime import datetime

import gi
gi.require_version("Gimp", "3.0")
gi.require_version("Gio", "2.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gio, GLib, GObject, Gegl


LOAD_PROC = "file-mib2-load"
EXPORT_PROC = "file-mib2-export"
PLUGIN_BINARY = os.path.splitext(os.path.basename(__file__))[0]
PLUGIN_VERSION = "1.1.3"
FORMAT_NAME = "MIB2STD BOOT Image"
MIME_TYPE = "image/mib2"
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mib2image_gimp3.log")
LOG_BACKUP_FILE = LOG_FILE + ".old"
LOG_MAX_BYTES = 128 * 1024  # 128 KiB per log file

LABEL_X = 160
LABEL_Y = 320
LABEL_WIDTH = 480
LABEL_HEIGHT = 100

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


TRANSLATIONS = {
    "en": {
        "load_doc_title": "Load MIB2STD boot image",
        "load_doc_help": (
            "Loads an MIB2STD PNG container and reconstructs the RGB image "
            "using the original MIB2 conversion formula."
        ),
        "export_doc_title": "Export MIB2STD boot image",
        "export_doc_help": (
            "Encodes a GIMP image as an MIB2STD grayscale/alpha PNG. "
            "Optionally limits color levels and extracts the 480×100 label "
            "area from 800×480 images."
        ),
        "attribution": "John Tomatos; GIMP 3.x port by MrGame11",
        "limit_colors_label": "Limit color levels",
        "limit_colors_help": (
            "0 disables color limiting; 2–256 sets the posterize levels "
            "per RGB channel."
        ),
        "extract_label_label": "Extract label to a separate file",
        "extract_label_help": (
            "For exact 800×480 images, the 480×100 area starting at "
            "X=160 / Y=320 is saved as *_lbl.mib."
        ),
        "export_dialog_title": "MIB2STD BOOT Image",
        "export_button": "Export",
        "help_button": "Help",
        "help_dialog_title": "MIB2 Export Help",
        "label_notice_title": "Label extraction not available",
        "label_notice_text": (
            "Label extraction was selected, but this image is {width}×{height}. "
            "A label is only extracted from images that are exactly 800×480 pixels. "
            "The main MIB file will still be exported normally without a separate "
            "*_lbl.mib file."
        ),
        "export_explanation": (
            "Color levels: Limits each RGB channel to the selected number of "
            "levels. For example, 8 levels allow up to 8³ = 512 RGB color "
            "combinations before MIB2 conversion. 0 disables limiting. "
            "Lower values may reduce file size, but can create visible "
            "color banding.\n\n"
            "Label: For 800×480 images, this optionally extracts the "
            "480×100 area at X=160 / Y=320 into a separate *_lbl.mib file. "
            "The extracted area in the main MIB file is replaced with the "
            "format's placeholder values.\n\n"
            "Image width: The image width must always be an even number of pixels. "
            "Images with an odd width cannot be exported to the MIB2 format."
        ),
        "remote_not_supported": "Remote files are not supported by this plug-in.",
        "width_even": "Invalid resolution: The image width must be even.",
        "mib_requires_graya": (
            "An MIB2 file must be an 8-bit PNG using grayscale and alpha."
        ),
        "unsupported_png_color": "Unsupported PNG color type.",
        "invalid_pixel_data": "Invalid pixel data: expected {expected}, got {actual}.",
        "not_png": "The file is not a valid PNG/MIB2 container.",
        "damaged_chunk": "Damaged PNG chunk.",
        "invalid_ihdr": "Invalid PNG IHDR chunk.",
        "invalid_image_size": "Invalid image size.",
        "only_8bit": "Only 8-bit PNG files are supported.",
        "unsupported_png_type": "PNG color type {color_type} is not supported.",
        "unsupported_compression": "Unsupported PNG compression method.",
        "interlaced_not_supported": "Interlaced PNG/MIB2 files are not supported.",
        "crc_error": "CRC error in PNG/MIB2 container.",
        "incomplete_png": "Incomplete PNG/MIB2 container.",
        "png_unpack_failed": "PNG data could not be decompressed: {error}",
        "invalid_png_length": (
            "Invalid PNG data length: expected {expected}, got {actual}."
        ),
        "unknown_png_filter": "Unknown PNG filter type {filter_type}.",
        "cannot_convert_rgb": "PNG color type cannot be converted to RGB.",
        "invalid_mib_pixels": "Invalid MIB2 pixel data.",
        "invalid_rgb_pixels": "Invalid RGB pixel data.",
        "progress_decode": "Decoding MIB2 image …",
        "progress_encode": "Encoding MIB2 image …",
        "opening": "Opening “{name}” …",
    },
    "de": {
        "load_doc_title": "MIB2STD-Bootbild laden",
        "load_doc_help": (
            "Lädt einen MIB2STD-PNG-Container und rekonstruiert das RGB-Bild "
            "mit der ursprünglichen MIB2-Konvertierungsformel."
        ),
        "export_doc_title": "MIB2STD-Bootbild exportieren",
        "export_doc_help": (
            "Kodiert ein GIMP-Bild als MIB2STD-Graustufen-/Alpha-PNG. "
            "Optional werden die Farbstufen begrenzt und bei 800×480 Pixeln "
            "der 480×100-Pixel-Labelbereich extrahiert."
        ),
        "attribution": "John Tomatos; GIMP-3.x-Portierung von MrGame11",
        "limit_colors_label": "Farbstufen begrenzen",
        "limit_colors_help": (
            "0 deaktiviert die Begrenzung; 2–256 legt die Posterize-Stufen "
            "pro RGB-Kanal fest."
        ),
        "extract_label_label": "Label in separate Datei extrahieren",
        "extract_label_help": (
            "Bei exakt 800×480 Pixeln wird der Bereich 480×100 Pixel ab "
            "X=160 / Y=320 als *_lbl.mib gespeichert."
        ),
        "export_dialog_title": "MIB2STD BOOT Image",
        "export_button": "Exportieren",
        "help_button": "Hilfe",
        "help_dialog_title": "Hilfe zum MIB2-Export",
        "label_notice_title": "Label-Extraktion nicht möglich",
        "label_notice_text": (
            "Die Label-Extraktion ist aktiviert, aber dieses Bild ist {width}×{height} Pixel groß. "
            "Ein Label wird nur bei Bildern mit exakt 800×480 Pixeln extrahiert. "
            "Die Haupt-MIB-Datei wird trotzdem normal exportiert, jedoch ohne separate "
            "*_lbl.mib-Datei."
        ),
        "export_explanation": (
            "Farbstufen: Begrenzt jeden RGB-Kanal auf die gewählte Anzahl von "
            "Stufen. Beispiel: 8 Stufen erlauben vor der MIB2-Konvertierung "
            "theoretisch bis zu 8³ = 512 RGB-Farbkombinationen. 0 deaktiviert "
            "die Begrenzung. Niedrigere Werte können die Datei verkleinern, "
            "aber sichtbare Farbstufen erzeugen.\n\n"
            "Label: Bei 800×480-Bildern wird optional der Bereich 480×100 "
            "Pixel ab X=160 / Y=320 als separate *_lbl.mib-Datei exportiert. "
            "Der extrahierte Bereich wird in der Haupt-MIB durch die "
            "Platzhalterwerte des Formats ersetzt.\n\n"
            "Bildbreite: Die Breite des Bildes muss immer eine gerade Anzahl von "
            "Pixeln haben. Bilder mit ungerader Breite können nicht in das "
            "MIB2-Format exportiert werden."
        ),
        "remote_not_supported": (
            "Remote-Dateien werden von diesem Plugin nicht unterstützt."
        ),
        "width_even": "Ungültige Auflösung: Die Bildbreite muss gerade sein.",
        "mib_requires_graya": (
            "Eine MIB2-Datei muss ein 8-Bit-PNG mit Graustufen- und "
            "Alphakanal sein."
        ),
        "unsupported_png_color": "Nicht unterstützter PNG-Farbtyp.",
        "invalid_pixel_data": (
            "Ungültige Pixeldaten: erwartet {expected}, erhalten {actual}."
        ),
        "not_png": "Die Datei ist kein gültiger PNG/MIB2-Container.",
        "damaged_chunk": "Beschädigter PNG-Chunk.",
        "invalid_ihdr": "Ungültiger PNG-IHDR-Chunk.",
        "invalid_image_size": "Ungültige Bildgröße.",
        "only_8bit": "Es werden nur 8-Bit-PNG-Dateien unterstützt.",
        "unsupported_png_type": (
            "PNG-Farbtyp {color_type} wird nicht unterstützt."
        ),
        "unsupported_compression": "Nicht unterstützte PNG-Kompressionsmethode.",
        "interlaced_not_supported": (
            "Interlaced PNG/MIB2-Dateien werden nicht unterstützt."
        ),
        "crc_error": "CRC-Fehler im PNG/MIB2-Container.",
        "incomplete_png": "Unvollständiger PNG/MIB2-Container.",
        "png_unpack_failed": (
            "PNG-Daten konnten nicht entpackt werden: {error}"
        ),
        "invalid_png_length": (
            "Ungültige PNG-Datenlänge: erwartet {expected}, erhalten {actual}."
        ),
        "unknown_png_filter": "Unbekannter PNG-Filtertyp {filter_type}.",
        "cannot_convert_rgb": (
            "PNG-Farbtyp kann nicht nach RGB konvertiert werden."
        ),
        "invalid_mib_pixels": "Ungültige MIB2-Pixeldaten.",
        "invalid_rgb_pixels": "Ungültige RGB-Pixeldaten.",
        "progress_decode": "MIB2-Bild wird dekodiert …",
        "progress_encode": "MIB2-Bild wird kodiert …",
        "opening": "„{name}“ wird geöffnet …",
    },
}


def _detect_language():
    """
    Detect the active GLib/system language.

    German is currently translated explicitly. All other languages use the
    English fallback, making it safe to add more translation dictionaries
    later without changing plug-in logic.
    """
    try:
        for language_name in GLib.get_language_names():
            normalized = language_name.lower().replace("-", "_")
            if normalized.startswith("de"):
                return "de"
    except Exception:
        pass
    return "en"


LANGUAGE = _detect_language()


def _t(key, **kwargs):
    """Return a localized string, falling back to English."""
    value = TRANSLATIONS.get(LANGUAGE, TRANSLATIONS["en"]).get(
        key, TRANSLATIONS["en"].get(key, key)
    )
    if kwargs:
        return value.format(**kwargs)
    return value


class Mib2Error(Exception):
    """User-facing MIB2/PNG format error."""


def _clamp_u8(value):
    return max(0, min(255, int(value)))


def _rotate_log_if_needed(incoming_bytes=0):
    """
    Keep mib2image.log at or below LOG_MAX_BYTES.

    When the next entry would exceed 1 MiB, the current log is moved to
    mib2image.log.old. Only one backup is retained.
    """
    try:
        current_size = os.path.getsize(LOG_FILE) if os.path.exists(LOG_FILE) else 0
        if current_size + incoming_bytes <= LOG_MAX_BYTES:
            return

        if os.path.exists(LOG_BACKUP_FILE):
            os.remove(LOG_BACKUP_FILE)
        if os.path.exists(LOG_FILE):
            os.replace(LOG_FILE, LOG_BACKUP_FILE)
    except Exception:
        pass


def _log(level, message):
    """Write diagnostics to stderr and, when possible, the rotating log."""
    # Local system date/time including the current UTC offset.
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    line = (
        f"[{timestamp}] "
        f"[mib2image {PLUGIN_VERSION}] {level}: {message}"
    )
    try:
        print(line, file=sys.stderr, flush=True)
    except Exception:
        pass

    try:
        encoded_size = len((line + "\n").encode("utf-8"))
        _rotate_log_if_needed(encoded_size)
        with open(LOG_FILE, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:
        # Logging must never prevent the plug-in from working.
        pass


def _glib_error(error):
    _log("ERROR", f"{type(error).__name__}: {error}")
    return GLib.Error(str(error))


def _load_success_values(image):
    """
    Create the standard successful LoadProcedure return values.

    This follows the pattern used by GIMP's own Python file loaders:
    a status value followed by the loaded Gimp.Image.
    """
    return Gimp.ValueArray.new_from_values([
        GObject.Value(Gimp.PDBStatusType, Gimp.PDBStatusType.SUCCESS),
        GObject.Value(Gimp.Image, image),
    ])


# ---------------------------------------------------------------------------
# Minimal PNG codec
#
# This plug-in intentionally handles PNG itself for the MIB2 container, so
# the two stored bytes (grayscale + alpha) are preserved exactly. GIMP's
# built-in PNG handler is still used for a temporary ordinary RGB image when
# exchanging pixels with GIMP.
# ---------------------------------------------------------------------------

def _paeth_predictor(a, b, c):
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _png_chunk(chunk_type, data):
    payload = chunk_type + data
    return (
        struct.pack(">I", len(data))
        + payload
        + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)
    )


def write_png(path, width, height, color_type, pixels):
    """Write an 8-bit, non-interlaced PNG using filter type 0."""
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        raise Mib2Error(_t("unsupported_png_color"))
    expected = width * height * channels
    if len(pixels) != expected:
        raise Mib2Error(
            _t("invalid_pixel_data", expected=expected, actual=len(pixels))
        )

    stride = width * channels
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # PNG filter: None
        start = y * stride
        raw.extend(pixels[start:start + stride])

    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    png = (
        PNG_SIGNATURE
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _png_chunk(b"IEND", b"")
    )

    with open(path, "wb") as handle:
        handle.write(png)


def read_png(path):
    """
    Read an 8-bit, non-interlaced PNG.

    Supported color types:
      0 = grayscale
      2 = RGB
      4 = grayscale + alpha
      6 = RGBA
    """
    with open(path, "rb") as handle:
        data = handle.read()

    if not data.startswith(PNG_SIGNATURE):
        raise Mib2Error(_t("not_png"))

    offset = len(PNG_SIGNATURE)
    width = height = bit_depth = color_type = None
    compressed = bytearray()
    saw_iend = False

    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        chunk_type = data[offset + 4:offset + 8]
        chunk_data_start = offset + 8
        chunk_data_end = chunk_data_start + length
        crc_end = chunk_data_end + 4

        if crc_end > len(data):
            raise Mib2Error(_t("damaged_chunk"))

        chunk_data = data[chunk_data_start:chunk_data_end]
        stored_crc = struct.unpack(">I", data[chunk_data_end:crc_end])[0]
        calculated_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        if stored_crc != calculated_crc:
            raise Mib2Error(_t("crc_error"))

        if chunk_type == b"IHDR":
            if length != 13:
                raise Mib2Error(_t("invalid_ihdr"))
            (
                width,
                height,
                bit_depth,
                color_type,
                compression,
                filter_method,
                interlace,
            ) = struct.unpack(">IIBBBBB", chunk_data)

            if width <= 0 or height <= 0:
                raise Mib2Error(_t("invalid_image_size"))
            if bit_depth != 8:
                raise Mib2Error(_t("only_8bit"))
            if color_type not in (0, 2, 4, 6):
                raise Mib2Error(
                    _t("unsupported_png_type", color_type=color_type)
                )
            if compression != 0 or filter_method != 0:
                raise Mib2Error(_t("unsupported_compression"))
            if interlace != 0:
                raise Mib2Error(_t("interlaced_not_supported"))

        elif chunk_type == b"IDAT":
            compressed.extend(chunk_data)

        elif chunk_type == b"IEND":
            saw_iend = True
            break

        offset = crc_end

    if width is None or not compressed or not saw_iend:
        raise Mib2Error(_t("incomplete_png"))

    channels = {0: 1, 2: 3, 4: 2, 6: 4}[color_type]
    bytes_per_pixel = channels
    stride = width * channels

    try:
        raw = zlib.decompress(bytes(compressed))
    except zlib.error as exc:
        raise Mib2Error(_t("png_unpack_failed", error=exc)) from exc

    expected = height * (stride + 1)
    if len(raw) != expected:
        raise Mib2Error(
            _t("invalid_png_length", expected=expected, actual=len(raw))
        )

    pixels = bytearray(width * height * channels)
    previous = bytearray(stride)
    source_offset = 0

    for y in range(height):
        filter_type = raw[source_offset]
        source_offset += 1
        row = bytearray(raw[source_offset:source_offset + stride])
        source_offset += stride

        if filter_type == 1:  # Sub
            for x in range(stride):
                left = row[x - bytes_per_pixel] if x >= bytes_per_pixel else 0
                row[x] = (row[x] + left) & 0xFF
        elif filter_type == 2:  # Up
            for x in range(stride):
                row[x] = (row[x] + previous[x]) & 0xFF
        elif filter_type == 3:  # Average
            for x in range(stride):
                left = row[x - bytes_per_pixel] if x >= bytes_per_pixel else 0
                up = previous[x]
                row[x] = (row[x] + ((left + up) // 2)) & 0xFF
        elif filter_type == 4:  # Paeth
            for x in range(stride):
                left = row[x - bytes_per_pixel] if x >= bytes_per_pixel else 0
                up = previous[x]
                up_left = (
                    previous[x - bytes_per_pixel] if x >= bytes_per_pixel else 0
                )
                row[x] = (
                    row[x] + _paeth_predictor(left, up, up_left)
                ) & 0xFF
        elif filter_type != 0:
            raise Mib2Error(_t("unknown_png_filter", filter_type=filter_type))

        start = y * stride
        pixels[start:start + stride] = row
        previous = row

    return width, height, color_type, bytes(pixels)


def png_pixels_to_rgb(width, height, color_type, pixels):
    """Convert supported PNG pixels to packed RGB bytes."""
    count = width * height

    if color_type == 2:
        return pixels

    rgb = bytearray(count * 3)

    if color_type == 6:
        for i in range(count):
            src = i * 4
            dst = i * 3
            rgb[dst:dst + 3] = pixels[src:src + 3]
        return bytes(rgb)

    if color_type == 0:
        for i, gray in enumerate(pixels):
            dst = i * 3
            rgb[dst:dst + 3] = bytes((gray, gray, gray))
        return bytes(rgb)

    if color_type == 4:
        for i in range(count):
            gray = pixels[i * 2]
            dst = i * 3
            rgb[dst:dst + 3] = bytes((gray, gray, gray))
        return bytes(rgb)

    raise Mib2Error(_t("cannot_convert_rgb"))


# ---------------------------------------------------------------------------
# Original MIB2 conversion logic, translated to Python 3.
# ---------------------------------------------------------------------------

def decode_mib2_to_rgb(width, height, graya_pixels):
    """Convert packed MIB2 grayscale+alpha pixels to ordinary RGB."""
    if width % 2 != 0:
        raise Mib2Error(_t("width_even"))
    if len(graya_pixels) != width * height * 2:
        raise Mib2Error(_t("invalid_mib_pixels"))

    rgb = bytearray(width * height * 3)
    Gimp.progress_init(_t("progress_decode"))

    for y in range(height):
        row_src = y * width * 2
        row_dst = y * width * 3

        for x in range(0, width, 2):
            pair_src = row_src + x * 2
            gb = graya_pixels[pair_src]
            gr = graya_pixels[pair_src + 2]

            for pair_offset in (0, 1):
                src = pair_src + pair_offset * 2
                dst = row_dst + (x + pair_offset) * 3
                green = graya_pixels[src + 1]

                blue = _clamp_u8(
                    green - 512 + ((gr * 4 + gb * 8) // 3)
                )
                red = _clamp_u8(
                    green - 512 + ((gb * 4 + gr * 8) // 3)
                )

                rgb[dst:dst + 3] = bytes((red, green, blue))

        Gimp.progress_update((y + 1) / float(height))

    Gimp.progress_end()
    return bytes(rgb)


def _posterize_channel(value, levels):
    """
    Posterize one 8-bit channel to approximately the same level model used
    by GIMP's posterize operation.
    """
    if levels <= 0:
        return value
    levels = max(2, min(256, levels))
    maximum = levels - 1
    step = (value * maximum + 127) // 255
    return (step * 255 + maximum // 2) // maximum


def posterize_rgb(rgb_pixels, levels):
    if levels <= 0:
        return rgb_pixels

    result = bytearray(len(rgb_pixels))
    for i, value in enumerate(rgb_pixels):
        result[i] = _posterize_channel(value, levels)
    return bytes(result)


def encode_rgb_to_mib2(width, height, rgb_pixels, extract_label):
    """Convert packed RGB pixels to MIB2 grayscale+alpha bytes."""
    if width % 2 != 0:
        raise Mib2Error(_t("width_even"))
    if len(rgb_pixels) != width * height * 3:
        raise Mib2Error(_t("invalid_rgb_pixels"))

    extract_label = bool(extract_label and width == 800 and height == 480)
    mib = bytearray(width * height * 2)
    label = bytearray(LABEL_WIDTH * LABEL_HEIGHT * 2) if extract_label else None

    Gimp.progress_init(_t("progress_encode"))

    for y in range(height):
        src_row = y * width * 3
        dst_row = y * width * 2

        for x in range(0, width, 2):
            src0 = src_row + x * 3
            src1 = src0 + 3

            r0, g0, b0 = rgb_pixels[src0:src0 + 3]
            r1, g1, b1 = rgb_pixels[src1:src1 + 3]

            # Even pixel: combine the two red values, exactly as in the
            # original plug-in. Python's // preserves Python 2 integer
            # division semantics, including negative values.
            averaged_red = math.isqrt((r0 * r0 + r1 * r1) // 2)
            packed0 = (
                ((b0 - averaged_red) // 2 + 128)
                + ((b0 - g0) // 2 + 128)
            ) // 2

            # Odd pixel: combine the two blue values.
            averaged_blue = math.isqrt((b1 * b1 + b0 * b0) // 2)
            packed1 = (
                ((r1 - averaged_blue) // 2 + 128)
                + ((r1 - g1) // 2 + 128)
            ) // 2

            pair = (
                (_clamp_u8(packed0), g0),
                (_clamp_u8(packed1), g1),
            )

            for pair_offset, pixel in enumerate(pair):
                current_x = x + pair_offset
                dest = dst_row + current_x * 2

                if (
                    extract_label
                    and LABEL_X <= current_x < LABEL_X + LABEL_WIDTH
                    and LABEL_Y <= y < LABEL_Y + LABEL_HEIGHT
                ):
                    label_dest = (
                        (current_x - LABEL_X)
                        + LABEL_WIDTH * (y - LABEL_Y)
                    ) * 2
                    label[label_dest:label_dest + 2] = bytes(pixel)
                    mib[dest:dest + 2] = bytes((128, 0))
                else:
                    mib[dest:dest + 2] = bytes(pixel)

        Gimp.progress_update((y + 1) / float(height))

    Gimp.progress_end()
    return bytes(mib), bytes(label) if label is not None else None


# ---------------------------------------------------------------------------
# GIMP integration
# ---------------------------------------------------------------------------

def _load_rgb_via_temp_png(width, height, rgb_pixels):
    """Fallback loader using GIMP's built-in PNG loader."""
    fd, temp_path = tempfile.mkstemp(prefix="mib2image-load-", suffix=".png")
    os.close(fd)
    try:
        write_png(temp_path, width, height, 2, rgb_pixels)
        temp_file = Gio.File.new_for_path(temp_path)
        image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, temp_file)
        if image is None:
            raise Mib2Error("GIMP konnte das temporäre RGB-Bild nicht laden.")
        _log("INFO", "RGB image created through temporary PNG fallback.")
        return image
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


def _load_rgb_direct(width, height, rgb_pixels):
    """
    Create the decoded RGB image directly with the GIMP 3 / GEGL API.
    """
    image = Gimp.Image.new(width, height, Gimp.ImageBaseType.RGB)
    if image is None:
        raise Mib2Error("GIMP konnte kein neues RGB-Bild erzeugen.")

    try:
        layer = Gimp.Layer.new(
            image,
            "background",
            width,
            height,
            Gimp.ImageType.RGB_IMAGE,
            100.0,
            Gimp.LayerMode.NORMAL,
        )
        if layer is None:
            raise Mib2Error("GIMP konnte keine RGB-Ebene erzeugen.")

        if not image.insert_layer(layer, None, 0):
            raise Mib2Error("Die RGB-Ebene konnte nicht in das Bild eingefügt werden.")

        buffer = layer.get_buffer()
        if buffer is None:
            raise Mib2Error("Der GEGL-Puffer der RGB-Ebene ist nicht verfügbar.")

        rect = Gegl.Rectangle.new(0, 0, width, height)

        # GEGL's introspection-friendly buffer API is exposed as set()
        # to Python bindings: rectangle, format name, byte data.
        buffer.set(rect, "R'G'B' u8", rgb_pixels)
        buffer.flush()
        layer.update(0, 0, width, height)

        _log("INFO", "RGB image created directly through GIMP/GEGL.")
        return image

    except Exception:
        try:
            image.delete()
        except Exception:
            pass
        raise


def _create_rgb_image(width, height, rgb_pixels):
    """Preferred direct GIMP/GEGL path with PNG fallback."""
    try:
        return _load_rgb_direct(width, height, rgb_pixels)
    except Exception as exc:
        _log(
            "WARNING",
            "Direct GIMP/GEGL RGB creation failed; "
            f"using temporary PNG fallback: {type(exc).__name__}: {exc}",
        )
        return _load_rgb_via_temp_png(width, height, rgb_pixels)


def _gimp_version_tuple():
    """Return the host GIMP version as a comparable integer tuple."""
    try:
        version_text = Gimp.version()
        numbers = re.findall(r"\d+", version_text)
        values = tuple(int(value) for value in numbers[:3])
        return values + (0,) * (3 - len(values))
    except Exception as exc:
        _log("WARNING", f"Could not determine GIMP version: {exc}")
        return None


def _prepare_export_image(image):
    """Duplicate, convert to RGB if needed, and flatten for export."""
    _log("INFO", "Export step: duplicating source image.")
    work_image = image.duplicate()
    if work_image is None:
        raise Mib2Error("Das Bild konnte nicht dupliziert werden.")

    try:
        if work_image.get_base_type() != Gimp.ImageBaseType.RGB:
            _log("INFO", "Export step: converting duplicated image to RGB.")
            result = work_image.convert_rgb()
            if result is False:
                raise Mib2Error(
                    "Das duplizierte Bild konnte nicht nach RGB konvertiert werden."
                )
        else:
            _log("INFO", "Export step: duplicated image is already RGB.")

        _log("INFO", "Export step: flattening duplicated image.")
        layer = work_image.flatten()
        if layer is None:
            raise Mib2Error("Das duplizierte Bild konnte nicht reduziert werden.")

        return work_image, layer
    except Exception:
        try:
            work_image.delete()
        except Exception:
            pass
        raise


def _apply_modern_gimp_posterize(drawable, levels):
    """Apply GIMP 3.2+'s preferred gimp:posterize filter."""
    _log(
        "INFO",
        f"Posterize: trying GIMP filter 'gimp:posterize' with {levels} levels.",
    )
    effect = Gimp.DrawableFilter.new(drawable, "gimp:posterize", "MIB2 Posterize")
    if effect is None:
        raise RuntimeError("Gimp.DrawableFilter.new() returned None.")

    config = effect.get_config()
    if config is None:
        raise RuntimeError("Could not obtain configuration for gimp:posterize.")

    config.set_property("levels", levels)
    effect.update()
    drawable.merge_filter(effect)
    drawable.update(0, 0, drawable.get_width(), drawable.get_height())

    _log(
        "INFO",
        f"Posterize method used: GIMP filter 'gimp:posterize' ({levels} levels).",
    )


def _apply_legacy_gimp_posterize(drawable, levels):
    """Apply native Drawable.posterize(), intended for GIMP 3.0/3.1."""
    _log(
        "INFO",
        f"Posterize: trying GIMP Drawable.posterize() with {levels} levels.",
    )
    result = drawable.posterize(levels)
    if result is False:
        raise RuntimeError("Drawable.posterize() returned False.")

    drawable.update(0, 0, drawable.get_width(), drawable.get_height())
    _log(
        "INFO",
        f"Posterize method used: GIMP Drawable.posterize() ({levels} levels).",
    )


def _save_work_image_to_rgb(work_image):
    """Exchange the prepared temporary GIMP image as ordinary RGB PNG."""
    fd, temp_path = tempfile.mkstemp(prefix="mib2image-export-", suffix=".png")
    os.close(fd)

    try:
        _log("INFO", f"Export step: writing temporary RGB PNG: {temp_path}")
        temp_file = Gio.File.new_for_path(temp_path)
        if not Gimp.file_save(
            Gimp.RunMode.NONINTERACTIVE, work_image, temp_file, None
        ):
            raise Mib2Error("GIMP konnte das temporäre RGB-PNG nicht exportieren.")

        _log("INFO", "Export step: reading temporary RGB PNG back into raw pixels.")
        width, height, color_type, pixels = read_png(temp_path)
        rgb_pixels = png_pixels_to_rgb(width, height, color_type, pixels)
        _log(
            "INFO",
            f"Export step: obtained RGB pixels ({width}x{height}, "
            f"PNG color type {color_type}).",
        )
        return width, height, rgb_pixels
    finally:
        try:
            os.unlink(temp_path)
            _log("INFO", "Export step: temporary RGB PNG removed.")
        except OSError:
            pass


def _export_image_to_rgb_via_temp_png(image, limit_colors):
    """
    Prepare RGB pixels for MIB2 export.

    GIMP 3.2+:
      gimp:posterize -> Drawable.posterize() -> internal Python fallback

    GIMP 3.0/3.1:
      Drawable.posterize() -> gimp:posterize -> internal Python fallback
    """
    requested_levels = int(limit_colors)

    if requested_levels <= 0:
        _log("INFO", "Posterize: disabled (color levels = 0).")
        work_image, _layer = _prepare_export_image(image)
        try:
            width, height, rgb_pixels = _save_work_image_to_rgb(work_image)
            return width, height, rgb_pixels, "disabled"
        finally:
            try:
                work_image.delete()
            except Exception:
                pass

    effective_levels = max(2, min(256, requested_levels))
    if effective_levels != requested_levels:
        _log(
            "WARNING",
            f"Posterize: requested value {requested_levels} normalized "
            f"to {effective_levels}.",
        )

    if effective_levels >= 256:
        _log(
            "INFO",
            "Posterize: 256 levels selected; no reduction is necessary "
            "for 8-bit RGB.",
        )
        work_image, _layer = _prepare_export_image(image)
        try:
            width, height, rgb_pixels = _save_work_image_to_rgb(work_image)
            return width, height, rgb_pixels, "no-op (256 levels)"
        finally:
            try:
                work_image.delete()
            except Exception:
                pass

    host_version = _gimp_version_tuple()
    try:
        host_version_text = Gimp.version()
    except Exception:
        host_version_text = "unknown"

    _log(
        "INFO",
        f"Posterize: host GIMP version={host_version_text}, "
        f"requested={requested_levels}, effective={effective_levels}.",
    )

    if host_version is not None and host_version < (3, 2, 0):
        methods = [
            ("GIMP Drawable.posterize()", _apply_legacy_gimp_posterize),
            ("GIMP filter gimp:posterize", _apply_modern_gimp_posterize),
        ]
    else:
        methods = [
            ("GIMP filter gimp:posterize", _apply_modern_gimp_posterize),
            ("GIMP Drawable.posterize()", _apply_legacy_gimp_posterize),
        ]

    for method_name, method in methods:
        work_image = None
        try:
            work_image, layer = _prepare_export_image(image)
            method(layer, effective_levels)
            width, height, rgb_pixels = _save_work_image_to_rgb(work_image)
            return width, height, rgb_pixels, method_name
        except Exception as exc:
            _log(
                "WARNING",
                f"Posterize native method failed: {method_name}: "
                f"{type(exc).__name__}: {exc}",
            )
        finally:
            if work_image is not None:
                try:
                    work_image.delete()
                except Exception:
                    pass

    _log(
        "WARNING",
        "Posterize: all native GIMP methods failed; "
        "using internal Python fallback.",
    )
    work_image, _layer = _prepare_export_image(image)
    try:
        width, height, rgb_pixels = _save_work_image_to_rgb(work_image)
    finally:
        try:
            work_image.delete()
        except Exception:
            pass

    rgb_pixels = posterize_rgb(rgb_pixels, effective_levels)
    _log(
        "INFO",
        f"Posterize method used: internal Python fallback "
        f"({effective_levels} levels).",
    )
    return width, height, rgb_pixels, "internal Python fallback"


def load_mib2_run(
    procedure,
    run_mode,
    file,
    metadata,
    flags,
    config,
    run_data,
):
    try:
        path = file.get_path()
        if not path:
            raise Mib2Error(_t("remote_not_supported"))

        _log("INFO", f"Load requested: source={path}")
        Gimp.progress_init(_t("opening", name=file.get_basename()))
        width, height, color_type, pixels = read_png(path)
        _log(
            "INFO",
            f"Load step: PNG/MIB2 container parsed "
            f"({width}x{height}, color type {color_type}).",
        )

        if color_type != 4:
            raise Mib2Error(_t("mib_requires_graya"))

        _log("INFO", "Load step: decoding MIB2 pixel data to RGB.")
        rgb_pixels = decode_mib2_to_rgb(width, height, pixels)
        _log("INFO", "Load step: creating GIMP RGB image.")
        image = _create_rgb_image(width, height, rgb_pixels)

        _log(
            "INFO",
            f"Loaded MIB2 image successfully: {width}x{height}, source={path}",
        )
        _log(
            "INFO",
            "Returning (Gimp.ValueArray[status, image], metadata_flags) to GIMP.",
        )
        # Gimp.RunLoadFunc has an in/out metadata flags argument.
        # In Python, LoadProcedure callbacks must return:
        #     (Gimp.ValueArray, flags)
        # This is also how GIMP's own file-openraster.py loader returns.
        return _load_success_values(image), flags

    except Exception as exc:
        return (
            procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR,
                _glib_error(exc),
            ),
            flags,
        )



def _find_spin_button(widget):
    """Recursively find a Gtk.SpinButton inside a composite GIMP UI widget."""
    try:
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
    except Exception:
        return None

    if isinstance(widget, Gtk.SpinButton):
        return widget

    try:
        if isinstance(widget, Gtk.Container):
            for child in widget.get_children():
                found = _find_spin_button(child)
                if found is not None:
                    return found
    except Exception:
        pass

    return None


def _configure_color_levels_widget(dialog, config):
    """
    Keep the user-facing color-level value in the valid set:
      0      = disabled
      2..256 = posterize levels

    The value 1 is skipped in the UI:
      0 -> 2 when increasing
      2 -> 0 when decreasing
    """
    try:
        widget = dialog.get_widget("lim-colors", GObject.TYPE_NONE)
    except Exception as exc:
        _log(
            "WARNING",
            f"Color levels UI: could not get property widget: "
            f"{type(exc).__name__}: {exc}",
        )
        return

    spin = _find_spin_button(widget)
    if spin is None:
        _log(
            "WARNING",
            "Color levels UI: no Gtk.SpinButton found; backend validation remains active.",
        )
        return

    state = {
        "previous_valid": int(config.get_property("lim-colors")),
        "adjusting": False,
    }

    def on_value_changed(spin_button):
        if state["adjusting"]:
            return

        value = int(round(spin_button.get_value()))

        if value == 1:
            previous = state["previous_valid"]

            # Beim Herunterzählen 2 -> 1 soll 0 erreicht werden.
            # In allen anderen Fällen wird 1 auf 2 angehoben.
            replacement = 0 if previous == 2 else 2

            state["adjusting"] = True
            try:
                spin_button.set_value(replacement)
                try:
                    config.set_property("lim-colors", replacement)
                except Exception:
                    pass

                _log(
                    "INFO",
                    f"Color levels UI: invalid value 1 skipped; normalized to {replacement}.",
                )
            finally:
                state["adjusting"] = False

            state["previous_valid"] = replacement
            return

        if value == 0 or 2 <= value <= 256:
            state["previous_valid"] = value

    spin.connect("value-changed", on_value_changed)
    _log(
        "INFO",
        "Color levels UI: valid values are 0 or 2-256; value 1 is skipped.",
    )


def _show_export_dialog(procedure, config):
    gi.require_version("GimpUi", "3.0")
    gi.require_version("Gtk", "3.0")
    from gi.repository import GimpUi, Gtk

    GimpUi.init(PLUGIN_BINARY)
    dialog = GimpUi.ProcedureDialog.new(
        procedure, config, _t("export_dialog_title")
    )

    dialog_items = [
        "lim-colors",
        "extract-label",
    ]

    # GIMP/PyGObject builds differ in the exposed binding name.
    filled = False
    fill_error = None

    if hasattr(dialog, "fill"):
        try:
            dialog.fill(dialog_items)
            _log(
                "INFO",
                "Export dialog: populated using ProcedureDialog.fill(list).",
            )
            filled = True
        except Exception as exc:
            fill_error = exc
            _log(
                "WARNING",
                f"Export dialog fill(list) failed: "
                f"{type(exc).__name__}: {exc}",
            )

    if not filled and hasattr(dialog, "fill_list"):
        try:
            dialog.fill_list(dialog_items)
            _log(
                "INFO",
                "Export dialog: populated using ProcedureDialog.fill_list(list).",
            )
            filled = True
        except Exception as exc:
            fill_error = exc
            _log(
                "WARNING",
                f"Export dialog fill_list(list) failed: "
                f"{type(exc).__name__}: {exc}",
            )

    if not filled:
        raise RuntimeError(
            "Could not populate GIMP export dialog with available "
            "ProcedureDialog API"
            + (f": {fill_error}" if fill_error else ".")
        )

    _configure_color_levels_widget(dialog, config)

    dialog.set_ok_label(_t("export_button"))

    def show_help(_button):
        """
        Open help without emitting a GtkDialog response.

        ProcedureDialog.run() returns a boolean validation result, not a
        Gtk.ResponseType. Therefore the Help button must be a normal button
        in the action area rather than a response button.
        """
        _log("INFO", "Export dialog: Help opened.")
        help_dialog = Gtk.MessageDialog(
            transient_for=dialog,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=_t("help_dialog_title"),
        )
        help_dialog.format_secondary_text(_t("export_explanation"))
        help_dialog.run()
        help_dialog.destroy()
        _log("INFO", "Export dialog: Help closed; returning to export options.")

    # Add a normal, non-response Help button. Unlike dialog.add_button(),
    # this does not emit GtkDialog::response and therefore does not cause
    # ProcedureDialog.run() to finish/cancel.
    try:
        help_button = Gtk.Button.new_with_label(_t("help_button"))
        help_button.connect("clicked", show_help)

        action_area = dialog.get_action_area()
        action_area.pack_start(help_button, False, False, 0)
        help_button.show()

        _log(
            "INFO",
            "Export dialog: non-response Help button added to action area.",
        )
    except Exception as exc:
        _log(
            "WARNING",
            f"Export dialog: could not add non-response Help button: "
            f"{type(exc).__name__}: {exc}",
        )

    # Important: GimpUi.ProcedureDialog.run() returns gboolean:
    # True = validated/export, False = cancelled.
    accepted = bool(dialog.run())

    if accepted:
        _log("INFO", "Export dialog: validated by user.")
    else:
        _log("INFO", "Export dialog: cancelled by user.")

    dialog.destroy()
    return accepted



def _show_label_extraction_notice(image):
    """
    Inform the user that label extraction will be skipped for non-800x480 images.

    This notice is shown only for interactive exports after the user confirms
    the export options. The main MIB export continues normally.
    """
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    try:
        width = image.get_width()
        height = image.get_height()
    except Exception:
        # Fallback for bindings that expose dimensions as properties.
        width = getattr(image, "width", 0)
        height = getattr(image, "height", 0)

    notice = Gtk.MessageDialog(
        transient_for=None,
        flags=Gtk.DialogFlags.MODAL,
        message_type=Gtk.MessageType.INFO,
        buttons=Gtk.ButtonsType.OK,
        text=_t("label_notice_title"),
    )
    notice.format_secondary_text(
        _t("label_notice_text", width=width, height=height)
    )
    notice.run()
    notice.destroy()

    _log(
        "INFO",
        f"Label extraction notice shown: image={width}x{height}; "
        "label extraction will be skipped.",
    )


def export_mib2_run(
    procedure,
    run_mode,
    image,
    file,
    options,
    metadata,
    config,
    run_data,
):
    try:
        if run_mode == Gimp.RunMode.INTERACTIVE:
            _log("INFO", "Export step: opening interactive export options dialog.")
            if not _show_export_dialog(procedure, config):
                _log("INFO", "Export cancelled after options dialog returned False.")
                return procedure.new_return_values(
                    Gimp.PDBStatusType.CANCEL, None
                )
            _log("INFO", "Export step: export options dialog accepted.")

        path = file.get_path()
        if not path:
            raise Mib2Error(_t("remote_not_supported"))

        limit_colors = int(config.get_property("lim-colors"))
        extract_label = bool(config.get_property("extract-label"))

        # Safety net: value 1 is not a valid posterize level.
        # Normalize it to the smallest active value, 2.
        if limit_colors == 1:
            _log(
                "WARNING",
                "Color levels: invalid value 1 received; normalized to 2.",
            )
            limit_colors = 2
            try:
                config.set_property("lim-colors", 2)
            except Exception:
                pass

        # Inform interactive users immediately after confirming the export
        # options if label extraction cannot be performed for this image size.
        if run_mode == Gimp.RunMode.INTERACTIVE and extract_label:
            try:
                current_width = image.get_width()
                current_height = image.get_height()
            except Exception:
                current_width = getattr(image, "width", 0)
                current_height = getattr(image, "height", 0)

            if current_width != 800 or current_height != 480:
                _show_label_extraction_notice(image)

        _log(
            "INFO",
            f"Export requested: target={path}, color_levels={limit_colors}, "
            f"extract_label={extract_label}.",
        )

        width, height, rgb_pixels, posterize_method = (
            _export_image_to_rgb_via_temp_png(image, limit_colors)
        )

        _log(
            "INFO",
            f"Export step: RGB preparation completed; "
            f"posterize_method={posterize_method}.",
        )

        if width % 2 != 0:
            raise Mib2Error(_t("width_even"))

        _log(
            "INFO",
            f"Export step: encoding RGB pixels to MIB2 ({width}x{height}).",
        )
        mib_pixels, label_pixels = encode_rgb_to_mib2(
            width, height, rgb_pixels, extract_label
        )

        _log("INFO", f"Export step: writing main MIB2 file: {path}")
        write_png(path, width, height, 4, mib_pixels)

        if label_pixels is not None:
            root, extension = os.path.splitext(path)
            label_path = root + "_lbl" + extension
            _log(
                "INFO",
                f"Export step: writing extracted label file: {label_path}",
            )
            write_png(
                label_path,
                LABEL_WIDTH,
                LABEL_HEIGHT,
                4,
                label_pixels,
            )
        elif extract_label:
            _log(
                "INFO",
                "Export step: label extraction requested but skipped because "
                "the image is not exactly 800x480. User was informed during "
                "interactive export when applicable.",
            )
        else:
            _log("INFO", "Export step: label extraction disabled.")

        try:
            main_size = os.path.getsize(path)
            _log(
                "INFO",
                f"Export completed successfully: target={path}, "
                f"size={main_size} bytes, "
                f"posterize_method={posterize_method}.",
            )
        except OSError:
            _log(
                "INFO",
                f"Export completed successfully: target={path}, "
                f"posterize_method={posterize_method}.",
            )

        return procedure.new_return_values(
            Gimp.PDBStatusType.SUCCESS, None
        )

    except Exception as exc:
        return procedure.new_return_values(
            Gimp.PDBStatusType.EXECUTION_ERROR,
            _glib_error(exc),
        )


class Mib2ImagePlugin(Gimp.PlugIn):
    def do_query_procedures(self):
        return [LOAD_PROC, EXPORT_PROC]

    def do_create_procedure(self, name):
        Gegl.init(None)

        if name == LOAD_PROC:
            procedure = Gimp.LoadProcedure.new(
                self,
                name,
                Gimp.PDBProcType.PLUGIN,
                load_mib2_run,
                None,
            )
            procedure.set_documentation(
                _t("load_doc_title"),
                _t("load_doc_help"),
                None,
            )
            procedure.set_attribution(
                _t("attribution"),
                "John Tomatos",
                "2021–2026",
            )
            procedure.set_format_name(FORMAT_NAME)
            procedure.set_menu_label(FORMAT_NAME)
            procedure.set_extensions("mib")
            procedure.set_mime_types(MIME_TYPE)
            procedure.set_handles_remote(False)
            return procedure

        if name == EXPORT_PROC:
            procedure = Gimp.ExportProcedure.new(
                self,
                name,
                Gimp.PDBProcType.PLUGIN,
                False,
                export_mib2_run,
                None,
            )
            procedure.set_documentation(
                _t("export_doc_title"),
                _t("export_doc_help"),
                None,
            )
            procedure.set_attribution(
                _t("attribution"),
                "John Tomatos",
                "2021–2026",
            )
            procedure.set_format_name(FORMAT_NAME)
            procedure.set_menu_label(FORMAT_NAME)
            procedure.set_extensions("mib")
            procedure.set_mime_types(MIME_TYPE)
            procedure.set_handles_remote(False)
            procedure.set_image_types("*")

            procedure.add_int_argument(
                "lim-colors",
                _t("limit_colors_label"),
                _t("limit_colors_help"),
                0,
                256,
                0,
                GObject.ParamFlags.READWRITE,
            )
            procedure.add_boolean_argument(
                "extract-label",
                _t("extract_label_label"),
                _t("extract_label_help"),
                True,
                GObject.ParamFlags.READWRITE,
            )
            return procedure

        return None


_log("INFO", f"Starting plug-in binary={PLUGIN_BINARY}, language={LANGUAGE}, gimp_version={Gimp.version() or "unknown"}, log_max_bytes={LOG_MAX_BYTES}")
Gimp.main(Mib2ImagePlugin.__gtype__, sys.argv)
