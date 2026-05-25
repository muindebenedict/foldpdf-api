import json
import io
import traceback
from http.server import BaseHTTPRequestHandler

try:
    import pikepdf
    from PIL import Image
    HAS_LIBS = True
except ImportError:
    HAS_LIBS = False


def compress_pdf_with_settings(pdf_bytes, scale=0.8, quality=40):
    if not HAS_LIBS:
        raise RuntimeError("Missing dependencies: pikepdf / Pillow")

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

            # Resize image based on frontend scale setting
            if scale < 1.0:
                new_width = int(img.width * scale)
                new_height = int(img.height * scale)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

            if img.mode != "RGB":
                img = img.convert("RGB")

            buf = io.BytesIO()
            # Convert quality float (e.g. 0.30) to integer (e.g. 30) for Pillow
            img.save(buf, format="JPEG", quality=int(quality * 100), optimize=True)

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
        "new_size": len(result)
    }


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)

            file_bytes = None
            scale = 0.8
            quality = 0.30

            content_type = self.headers.get('Content-Type', '')
            if 'boundary=' in content_type:
                boundary = content_type.split('boundary=')[-1].encode()
                parts = body.split(b'--' + boundary)
                
                for part in parts:
                    if b'Content-Disposition' not in part:
                        continue
                    if b'name="file"' in part:
                        content = part.split(b'\r\n\r\n', 1)[-1]
                        if content.endswith(b'\r\n'): content = content[:-2]
                        if content.endswith(b'--'): content = content[:-2]
                        file_bytes = content
                    elif b'name="scale"' in part:
                        content = part.split(b'\r\n\r\n', 1)[-1]
                        if content.endswith(b'\r\n'): content = content[:-2]
                        scale = float(content.decode().strip())
                    elif b'name="quality"' in part:
                        content = part.split(b'\r\n\r\n', 1)[-1]
                        if content.endswith(b'\r\n'): content = content[:-2]
                        quality = float(content.decode().strip())
            else:
                file_bytes = body

            if not file_bytes:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'{"error": "No file received"}')
                return

            result = compress_pdf_with_settings(file_bytes, scale, quality)

            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(result["pdf_bytes"])))
            
            # CORS Headers
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Original-Size, X-New-Size, X-Images-Processed")
            self.send_header("Access-Control-Expose-Headers", "X-Original-Size, X-New-Size, X-Images-Processed")
            
            # Track sizes
            self.send_header("X-Original-Size", str(result["original_size"]))
            self.send_header("X-New-Size", str(result["new_size"]))
            self.end_headers()

            self.wfile.write(result["pdf_bytes"])

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Original-Size, X-New-Size, X-Images-Processed")
        self.send_header("Access-Control-Expose-Headers", "X-Original-Size, X-New-Size, X-Images-Processed")
        self.end_headers()
