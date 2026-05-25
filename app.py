from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
import io
import traceback

try:
    import pikepdf
    from PIL import Image
    HAS_LIBS = True
except ImportError:
    HAS_LIBS = False

app = Flask(__name__)
CORS(app)  # Allow ALL origins - fixes your fetch error permanently

@app.route('/')
def home():
    return 'FoldPDF Compression API is running!'

@app.route('/api/compress', methods=['POST', 'OPTIONS'])
def compress_pdf():
    if request.method == 'OPTIONS':
        return '', 200  # Handle CORS preflight
    
    if not HAS_LIBS:
        return jsonify({"error": "PDF libraries not installed"}), 500
    
    try:
        # Get the uploaded file
        if 'file' not in request.files:
            return jsonify({"error": "No file provided"}), 400
        
        file = request.files['file']
        mode = request.form.get('mode', 'smart')
        
        # Read PDF bytes
        pdf_bytes = file.read()
        
        # Quality mapping
        quality_map = {
            "ultra": 25,
            "smart": 40,
            "quality": 60
        }
        quality = quality_map.get(mode, 40)
        
        # Scale mapping
        scale = 0.7 if mode == "ultra" else (0.8 if mode == "smart" else 1.0)
        
        # Process PDF
        pdf = pikepdf.open(io.BytesIO(pdf_bytes))
        processed = 0
        skipped = 0
        
        for obj in pdf.objects:
            if not hasattr(obj, "get") or obj.get("/Subtype") != "/Image":
                continue
            
            try:
                raw = obj.read_raw_bytes()
                if not raw:
                    skipped += 1
                    continue
                
                img = Image.open(io.BytesIO(raw))
                
                # Resize if needed
                if scale < 1.0:
                    new_size = (int(img.width * scale), int(img.height * scale))
                    img = img.resize(new_size, Image.Resampling.LANCZOS)
                
                # Convert to RGB for JPEG
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
                
                # Save compressed JPEG
                buf = io.BytesIO()
                img.save(buf, format='JPEG', quality=quality, optimize=True)
                new_data = buf.getvalue()
                
                # Only replace if we actually saved space
                if len(new_data) >= len(raw) * 0.95:
                    skipped += 1
                    continue
                
                obj.write(new_data)
                obj["/Filter"] = pikepdf.Name("/DCTDecode")
                if "/DecodeParms" in obj:
                    del obj["/DecodeParms"]
                processed += 1
                
            except Exception:
                skipped += 1
                continue
        
        # Save result
        out = io.BytesIO()
        pdf.save(out)
        out.seek(0)
        result_bytes = out.read()
        
        # Return compressed PDF with headers
        return send_file(
            io.BytesIO(result_bytes),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'foldpdf-compressed-{mode}.pdf',
            headers={
                'X-Original-Size': str(len(pdf_bytes)),
                'X-New-Size': str(len(result_bytes)),
                'X-Images-Processed': str(processed)
            }
        )
        
    except Exception as e:
        return jsonify({
            "error": str(e),
            "details": traceback.format_exc()
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
