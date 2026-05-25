import json
import io
from http.server import BaseHTTPRequestHandler

# NOTE: keep imports, but they may fail on Vercel later (we’ll fix that next step)
try:
    import pikepdf
    from PIL import Image
    HAS_LIBS = True
except ImportError:
    HAS_LIBS = False


def compress_pdf(pdf_bytes, mode="smart"):
    if not HAS_LIBS:
        raise RuntimeError("Missing dependencies: pikepdf / Pillow")

    quality_map = {
        "ultra": 25,
        "smart": 40,
        "quality": 60
    }

    quality = quality_map.get(mode, 40)

    pdf = pikepdf.open(io.BytesIO(pdf_bytes))

    processed = 0
    skipped = 0

    for obj in pdf.objects:
        if not hasattr(obj, "get"):
            continue

        if obj.get("/Subtype") != "/Image":
            continue

        try:
            raw = obj.read_raw_bytes()
            if not raw:
                skipped += 1
                continue

            img = Image.open(io.BytesIO(raw))

            if img.mode != "RGB":
                img = img.convert("RGB")

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=True)

            new_data = buf.getvalue()

            if len(new_data) >= len(raw) * 0.95:
                skipped += 1
                continue

            obj.write(new_data)
            obj["/Filter"] = pikepdf.Name("/DCTDecode")

            processed += 1

        except Exception:
            skipped += 1
            continue

    out = io.BytesIO()
    pdf.save(out)
    out.seek(0)

    result = out.read()

    return {
        "pdf_bytes": result,
        "processed": processed,
        "skipped": skipped,
        "original_size": len(pdf_bytes),
        "new_size": len(result),
        "mode": mode,
        "quality": quality
    }


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)

            file_bytes = body

            if not file_bytes:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"No file provided")
                return

            result = compress_pdf(file_bytes)

            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            self.wfile.write(result["pdf_bytes"])

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            self.wfile.write(json.dumps({
                "error": str(e)
            }).encode())
