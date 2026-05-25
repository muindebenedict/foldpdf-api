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


def compress_pdf(pdf_bytes, mode='smart'):
    if not HAS_LIBS:
        raise RuntimeError("pikepdf and Pillow not installed")

    quality_map = {'ultra': 25, 'smart': 40, 'quality': 60}
    target_quality = quality_map.get(mode, 40)

    pdf = pikepdf.open(io.BytesIO(pdf_bytes))
    images_processed = 0
    images_skipped = 0

    for obj in pdf.objects:
        if not hasattr(obj, 'get'):
            continue

        subtype = obj.get('/Subtype')
        if subtype != '/Image':
            continue

        width = int(obj.get('/Width', 0))
        height = int(obj.get('/Height', 0))
        if width == 0 or height == 0:
            continue

        filters = obj.get('/Filter', [])
        if isinstance(filters, pikepdf.Name):
            filters = [filters]

        raw = obj.read_raw_bytes()

        try:
            img = Image.open(io.BytesIO(raw))

            if img.mode in ('RGBA', 'P', 'LA'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                if img.mode in ('RGBA', 'LA'):
                    background.paste(img, mask=img.split()[-1])
                    img = background
                else:
                    img = img.convert('RGB')
            elif img.mode != 'RGB':
                img = img.convert('RGB')

            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=target_quality, optimize=True)
            new_data = buf.getvalue()

            if len(new_data) >= len(raw) * 0.95:
                images_skipped += 1
                continue

            obj.write(new_data)
            obj['/Filter'] = pikepdf.Name('/DCTDecode')

            if '/DecodeParms' in obj:
                del obj['/DecodeParms']

            images_processed += 1

        except Exception:
            images_skipped += 1
            continue

    out_buf = io.BytesIO()
    pdf.save(
        out_buf,
        compress_streams=True,
        object_stream_mode=pikepdf.ObjectStreamMode.generate
    )
    out_buf.seek(0)

    result = out_buf.read()

    return {
        'pdf_bytes': result,
        'images_processed': images_processed,
        'images_skipped': images_skipped,
        'original_size': len(pdf_bytes),
        'new_size': len(result),
        'mode': mode,
        'quality': target_quality
    }


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)

            boundary = self.headers.get('Content-Type', '').split('boundary=')[-1]
            parts = body.split(b'--' + boundary.encode())

            file_bytes = None
            mode = 'smart'

            for part in parts:
                if b'Content-Disposition' not in part:
                    continue

                if b'name="file"' in part:
                    content = part.split(b'\r\n\r\n', 1)[-1]
                    if content.endswith(b'\r\n'):
                        content = content[:-2]
                    file_bytes = content

                elif b'name="mode"' in part:
                    content = part.split(b'\r\n\r\n', 1)[-1]
                    if content.endswith(b'\r\n'):
                        content = content[:-2]
                    mode = content.decode().strip()

            if not file_bytes:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'{"error": "No file provided"}')
                return

            result = compress_pdf(file_bytes, mode)

            self.send_response(200)
            self.send_header('Content-Type', 'application/pdf')
            self.send_header('Content-Length', str(len(result['pdf_bytes'])))
            self.send_header('X-Images-Processed', str(result['images_processed']))
            self.send_header('X-Original-Size', str(result['original_size']))
            self.send_header('X-New-Size', str(result['new_size']))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            self.wfile.write(result['pdf_bytes'])

        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            self.wfile.write(json.dumps({
                'error': str(e),
                'details': traceback.format_exc()
            }).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
