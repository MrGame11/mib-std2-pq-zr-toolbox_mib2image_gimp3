#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# mib2image_3.0
# MIB2STD boot image loader/exporter for GIMP 3.x
#
# Version: 1.0.0
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
mib2image_3.0
===============

MIB2STD boot image loader and exporter for GIMP 3.x.

Version: 1.0.0
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


__version__ = "1.0.2"
__author__ = "MrGame11"
__license__ = "GPL-3.0-or-later"
__url__ = "https://github.com/MrGame11/mib-std2-pq-zr-toolbox_mib2image_gimp3"

import math
import os
import struct
import sys
import tempfile
import zlib

import gi
gi.require_version("Gimp", "3.0")
gi.require_version("Gio", "2.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gimp, Gio, GLib, GObject, Gegl


LOAD_PROC = "file-mib2-load"
EXPORT_PROC = "file-mib2-export"
PLUGIN_BINARY = os.path.splitext(os.path.basename(__file__))[0]
PLUGIN_VERSION = "1.0.2"
FORMAT_NAME = "MIB2STD BOOT Image"
MIME_TYPE = "image/mib2"
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mib2image.log")

LABEL_X = 160
LABEL_Y = 320
LABEL_WIDTH = 480
LABEL_HEIGHT = 100

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class Mib2Error(Exception):
    """User-facing MIB2/PNG format error."""


def _clamp_u8(value):
    return max(0, min(255, int(value)))


def _log(level, message):
    """Write diagnostics to stderr and, when possible, mib2image.log."""
    line = f"[mib2image {PLUGIN_VERSION}] {level}: {message}"
    try:
        print(line, file=sys.stderr, flush=True)
    except Exception:
        pass

    try:
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
        raise Mib2Error("Nicht unterstützter PNG-Farbtyp.")
    expected = width * height * channels
    if len(pixels) != expected:
        raise Mib2Error(
            f"Ungültige Pixeldaten: erwartet {expected}, erhalten {len(pixels)}."
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
        raise Mib2Error("Die Datei ist kein gültiger PNG/MIB2-Container.")

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
            raise Mib2Error("Beschädigter PNG-Chunk.")

        chunk_data = data[chunk_data_start:chunk_data_end]
        stored_crc = struct.unpack(">I", data[chunk_data_end:crc_end])[0]
        calculated_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        if stored_crc != calculated_crc:
            raise Mib2Error("CRC-Fehler im PNG/MIB2-Container.")

        if chunk_type == b"IHDR":
            if length != 13:
                raise Mib2Error("Ungültiger PNG-IHDR-Chunk.")
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
                raise Mib2Error("Ungültige Bildgröße.")
            if bit_depth != 8:
                raise Mib2Error("Es werden nur 8-Bit-PNG-Dateien unterstützt.")
            if color_type not in (0, 2, 4, 6):
                raise Mib2Error(
                    f"PNG-Farbtyp {color_type} wird nicht unterstützt."
                )
            if compression != 0 or filter_method != 0:
                raise Mib2Error("Nicht unterstützte PNG-Kompressionsmethode.")
            if interlace != 0:
                raise Mib2Error("Interlaced PNG/MIB2-Dateien werden nicht unterstützt.")

        elif chunk_type == b"IDAT":
            compressed.extend(chunk_data)

        elif chunk_type == b"IEND":
            saw_iend = True
            break

        offset = crc_end

    if width is None or not compressed or not saw_iend:
        raise Mib2Error("Unvollständiger PNG/MIB2-Container.")

    channels = {0: 1, 2: 3, 4: 2, 6: 4}[color_type]
    bytes_per_pixel = channels
    stride = width * channels

    try:
        raw = zlib.decompress(bytes(compressed))
    except zlib.error as exc:
        raise Mib2Error(f"PNG-Daten konnten nicht entpackt werden: {exc}") from exc

    expected = height * (stride + 1)
    if len(raw) != expected:
        raise Mib2Error(
            f"Ungültige PNG-Datenlänge: erwartet {expected}, erhalten {len(raw)}."
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
            raise Mib2Error(f"Unbekannter PNG-Filtertyp {filter_type}.")

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

    raise Mib2Error("PNG-Farbtyp kann nicht nach RGB konvertiert werden.")


# ---------------------------------------------------------------------------
# Original MIB2 conversion logic, translated to Python 3.
# ---------------------------------------------------------------------------

def decode_mib2_to_rgb(width, height, graya_pixels):
    """Convert packed MIB2 grayscale+alpha pixels to ordinary RGB."""
    if width % 2 != 0:
        raise Mib2Error("Ungültige Auflösung: Die Breite muss gerade sein.")
    if len(graya_pixels) != width * height * 2:
        raise Mib2Error("Ungültige MIB2-Pixeldaten.")

    rgb = bytearray(width * height * 3)
    Gimp.progress_init("MIB2-Bild wird dekodiert …")

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
        raise Mib2Error("Ungültige Auflösung: Die Breite muss gerade sein.")
    if len(rgb_pixels) != width * height * 3:
        raise Mib2Error("Ungültige RGB-Pixeldaten.")

    extract_label = bool(extract_label and width == 800 and height == 480)
    mib = bytearray(width * height * 2)
    label = bytearray(LABEL_WIDTH * LABEL_HEIGHT * 2) if extract_label else None

    Gimp.progress_init("MIB2-Bild wird kodiert …")

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


def _export_image_to_rgb_via_temp_png(image):
    work_image = image.duplicate()
    if work_image is None:
        raise Mib2Error("Das Bild konnte nicht dupliziert werden.")

    fd, temp_path = tempfile.mkstemp(prefix="mib2image-export-", suffix=".png")
    os.close(fd)

    try:
        if work_image.get_base_type() != Gimp.ImageBaseType.RGB:
            work_image.convert_rgb()

        work_image.flatten()

        temp_file = Gio.File.new_for_path(temp_path)
        if not Gimp.file_save(
            Gimp.RunMode.NONINTERACTIVE, work_image, temp_file, None
        ):
            raise Mib2Error("GIMP konnte das temporäre RGB-PNG nicht exportieren.")

        width, height, color_type, pixels = read_png(temp_path)
        return width, height, png_pixels_to_rgb(
            width, height, color_type, pixels
        )
    finally:
        try:
            work_image.delete()
        except Exception:
            pass
        try:
            os.unlink(temp_path)
        except OSError:
            pass


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
            raise Mib2Error("Remote-Dateien werden von diesem Plugin nicht unterstützt.")

        Gimp.progress_init(f"„{file.get_basename()}“ wird geöffnet …")
        width, height, color_type, pixels = read_png(path)

        if color_type != 4:
            raise Mib2Error(
                "Eine MIB2-Datei muss ein 8-Bit-PNG mit "
                "Graustufen- und Alphakanal sein."
            )

        rgb_pixels = decode_mib2_to_rgb(width, height, pixels)
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


def _show_export_dialog(procedure, config):
    gi.require_version("GimpUi", "3.0")
    from gi.repository import GimpUi

    GimpUi.init(PLUGIN_BINARY)
    dialog = GimpUi.ProcedureDialog.new(
        procedure, config, "MIB2STD BOOT Image"
    )
    dialog.fill(["lim-colors", "extract-label"])
    accepted = dialog.run()
    dialog.destroy()
    return accepted


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
            if not _show_export_dialog(procedure, config):
                return procedure.new_return_values(
                    Gimp.PDBStatusType.CANCEL, None
                )

        path = file.get_path()
        if not path:
            raise Mib2Error("Remote-Dateien werden von diesem Plugin nicht unterstützt.")

        limit_colors = int(config.get_property("lim-colors"))
        extract_label = bool(config.get_property("extract-label"))

        width, height, rgb_pixels = _export_image_to_rgb_via_temp_png(image)

        if width % 2 != 0:
            raise Mib2Error("Ungültige Auflösung: Die Breite muss gerade sein.")

        if limit_colors > 0:
            rgb_pixels = posterize_rgb(rgb_pixels, limit_colors)

        mib_pixels, label_pixels = encode_rgb_to_mib2(
            width, height, rgb_pixels, extract_label
        )

        write_png(path, width, height, 4, mib_pixels)

        if label_pixels is not None:
            root, extension = os.path.splitext(path)
            label_path = root + "_lbl" + extension
            write_png(
                label_path,
                LABEL_WIDTH,
                LABEL_HEIGHT,
                4,
                label_pixels,
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
                "MIB2STD-Bootbild laden",
                "Lädt einen MIB2STD-PNG-Container und rekonstruiert "
                "das RGB-Bild mit der ursprünglichen MIB2-Formel.",
                None,
            )
            procedure.set_attribution(
                "John Tomatos; GIMP-3-Portierung",
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
                "MIB2STD-Bootbild exportieren",
                "Kodiert ein GIMP-Bild als MIB2STD-Graustufen-/Alpha-PNG. "
                "Optional werden die Farben begrenzt und bei 800×480 Pixeln "
                "das 480×100-Pixel-Label extrahiert.",
                None,
            )
            procedure.set_attribution(
                "John Tomatos; GIMP-3-Portierung",
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
                "Farbstufen begrenzen",
                "0 deaktiviert die Begrenzung; 2–256 legt die "
                "Posterize-Stufen pro RGB-Kanal fest.",
                0,
                256,
                0,
                GObject.ParamFlags.READWRITE,
            )
            procedure.add_boolean_argument(
                "extract-label",
                "Label in separate Datei extrahieren",
                "Bei exakt 800×480 Pixeln wird der Bereich 480×100 Pixel "
                "ab Position 160/320 als *_lbl.mib gespeichert.",
                True,
                GObject.ParamFlags.READWRITE,
            )
            return procedure

        return None


_log("INFO", f"Starting plug-in binary={PLUGIN_BINARY}")
Gimp.main(Mib2ImagePlugin.__gtype__, sys.argv)
