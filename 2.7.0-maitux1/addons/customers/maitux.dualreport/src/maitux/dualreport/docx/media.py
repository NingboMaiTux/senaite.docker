# -*- coding: utf-8 -*-
"""Image helpers for the Word generator.

Resolves <img> sources (data URIs or portal URLs) into embeddable bytes and
computes intrinsic sizes.

Supported inputs:
  * PNG / JPEG / GIF            - embedded as-is
  * BMP                         - re-encoded to PNG (Word-safe), via Pillow
                                  if available (Pillow ships with the image
                                  deps of senaite.core)
  * SVG (data URIs, incl. the
    base64 SVG that the impress
    JS produces for charts and   - rasterized to PNG via CairoSVG when
    the default senaite logo)      available, otherwise skipped with a log
"""
import base64
import binascii
import io
import re
import struct

from maitux.dualreport.config import logger

_RE_SVG_WIDTH = re.compile(r'width="(\d+)(?:px)?"')
_RE_SVG_HEIGHT = re.compile(r'height="(\d+)(?:px)?"')


def parse_data_uri(src):
    """Parse a data: URI.

    :returns: (mime_type, raw_bytes) or (None, None)
    """
    if not src or not src.lower().startswith("data:"):
        return None, None
    try:
        header, _, payload = src.partition(",")
        meta = header[5:]  # strip "data:"
        mime = meta.split(";")[0].lower() or "application/octet-stream"
        if ";base64" in meta:
            raw = base64.b64decode(payload)
        else:
            raw = payload  # percent-decoding would be needed; rarely used
        return mime, raw
    except (ValueError, TypeError, binascii.Error):
        logger.warn("maitux.dualreport: could not decode data URI")
        return None, None


def sniff_image_size(data):
    """Return (width_px, height_px) for PNG/JPEG/GIF bytes or (None, None).

    Pure stdlib header parsing, only used as a fallback when the report HTML
    does not carry an explicit width/height.
    """
    try:
        if data[:8] == "\x89PNG\r\n\x1a\n":
            # PNG: IHDR chunk at offset 16
            w, h = struct.unpack(">II", data[16:24])
            return int(w), int(h)
        if data[:6] in ("GIF87a", "GIF89a"):
            w, h = struct.unpack("<HH", data[6:10])
            return int(w), int(h)
        if data[:2] == "\xff\xd8":
            # JPEG: walk the segments looking for SOFn markers
            offset = 2
            length = len(data)
            while offset < length:
                if data[offset] != 0xFF:
                    offset += 1
                    continue
                marker = ord(data[offset + 1])
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                              0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    # SOFn: precision(1) height(2) width(2)
                    h, w = struct.unpack(">HH", data[offset + 5:offset + 9])
                    return int(w), int(h)
                if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                    offset += 2
                    continue
                seg_len = struct.unpack(">H", data[offset + 2:offset + 4])[0]
                offset += 2 + seg_len
    except (struct.error, IndexError):
        pass
    return None, None


def _looks_like_bmp(data):
    return data[:2] == "BM"


def _looks_like_svg(data):
    head = data[:400].lstrip()
    return head[:4] == "<svg" or (head[:5] == "<?xml" and "<svg" in head[:400])


def _bmp_to_png(data):
    """Re-encode BMP bytes to PNG via Pillow (returns None on failure)."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        img.load()
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()
    except Exception as exc:  # noqa: B902
        logger.warn("maitux.dualreport: BMP->PNG conversion failed: %s" % exc)
        return None


def _svg_to_png(data):
    """Rasterize SVG bytes to PNG via CairoSVG (returns None on failure)."""
    try:
        import cairosvg
    except ImportError:
        logger.warn("maitux.dualreport: CairoSVG not available, "
                    "skipping SVG image")
        return None
    try:
        return cairosvg.svg2png(bytestring=data)
    except Exception:  # noqa: B902
        pass
    # fall back to an explicit output width
    try:
        m = _RE_SVG_WIDTH.search(data[:2000])
        width = int(m.group(1)) if m else 600
        return cairosvg.svg2png(bytestring=data, output_width=width)
    except Exception as exc:  # noqa: B902
        logger.warn("maitux.dualreport: SVG->PNG conversion failed: %s" % exc)
        return None


def normalize_image(data, mime=None):
    """Return (png_like_data, width_px, height_px) or None.

    BMP and SVG payloads are converted to PNG; PNG/JPEG/GIF are kept.
    """
    if not data:
        return None
    if _looks_like_bmp(data) or (mime or "").split(";")[0] == "image/bmp":
        converted = _bmp_to_png(data)
        if converted:
            data = converted
    elif _looks_like_svg(data) or \
            (mime or "").split(";")[0] in ("image/svg+xml", "image/svg"):
        converted = _svg_to_png(data)
        if not converted:
            return None
        data = converted
    width, height = sniff_image_size(data)
    return data, width, height


def ext_for_mime(mime):
    """Map a mime type to a file extension (defaults to png)."""
    if not mime:
        return "png"
    simple = mime.split(";")[0].strip().lower()
    return {
        "image/png": "png",
        "image/jpeg": "jpeg",
        "image/jpg": "jpeg",
        "image/gif": "gif",
        "image/bmp": "bmp",
        "image/tiff": "tiff",
    }.get(simple, "png")


def resolve_image(src, fetch_url=None):
    """Resolve an image source to (ext, data, width_px, height_px).

    :param src: img src attribute (data URI or http(s) URL)
    :param fetch_url: optional callable(url) -> bytes used for portal URLs
    :returns: (ext, data, width_px, height_px) or None
    """
    mime, data = parse_data_uri(src)
    if data is None and src and fetch_url is not None:
        try:
            data = fetch_url(src)
            if data:
                mime = None
        except Exception as exc:  # noqa: B902 - never break the report
            logger.warn("maitux.dualreport: fetch of '%s' failed: %s"
                        % (src, exc))
            data = None
    if not data:
        return None
    normalized = normalize_image(data, mime)
    if normalized is None:
        return None
    data, width, height = normalized
    return "png", data, width, height
