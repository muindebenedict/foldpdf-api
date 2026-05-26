from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
import io
import traceback
import subprocess
import tempfile
import os

app = Flask(__name__)
CORS(app)

@app.route('/')
def home():
    return 'FoldPDF Compression API is running!'

@app.route('/api/compress', methods=['POST', 'OPTIONS'])
def compress_pdf():
    if request.method == 'OPTIONS':
        return '', 200

    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file provided"}), 400

        file = request.files['file']
        mode = request.form.get('mode', 'smart')

        pdf_bytes = file.read()
        original_size = len(pdf_bytes)

        gs_settings = {
            "ultra":   "/screen",
            "smart":   "/ebook",
            "quality": "/printer"
        }
        setting = gs_settings.get(mode, "/ebook")

        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_in:
            tmp_in.write(pdf_bytes)
            input_path = tmp_in.name

        output_path = input_path.replace('.pdf', '_out.pdf')

        try:
            # Base flags for all modes
            cmd = [
                'gs',
                '-sDEVICE=pdfwrite',
                '-dCompatibilityLevel=1.4',
                f'-dPDFSETTINGS={setting}',
                '-dNOPAUSE',
                '-dQUIET',
                '-dBATCH',
                '-dDetectDuplicateImages=true',
                '-dCompressFonts=true',
                '-dSubsetFonts=true',
            ]

            # Mode-specific extra flags
            if mode == "ultra":
                cmd += [
                    '-dColorImageResolution=72',
                    '-dGrayImageResolution=72',
                    '-dMonoImageResolution=72',
                    '-dColorImageDownsampleType=/Bicubic',
                    '-dGrayImageDownsampleType=/Bicubic',
                    '-dDownsampleColorImages=true',
                    '-dDownsampleGrayImages=true',
                    '-dDownsampleMonoImages=true',
                    '-dColorImageFilter=/DCTEncode',
                    '-dAutoFilterColorImages=false',
                    '-dJPEGQ=20',
                ]
            elif mode == "smart":
                cmd += [
                    '-dColorImageResolution=100',
                    '-dGrayImageResolution=100',
                    '-dMonoImageResolution=100',
                    '-dColorImageDownsampleType=/Bicubic',
                    '-dGrayImageDownsampleType=/Bicubic',
                    '-dDownsampleColorImages=true',
                    '-dDownsampleGrayImages=true',
                    '-dJPEGQ=40',
                ]
            # quality mode uses /printer defaults — no extra flags needed

            cmd += [
                f'-sOutputFile={output_path}',
                input_path
            ]

            result = subprocess.run(cmd, capture_output=True, timeout=120)

            if result.returncode != 0:
                return jsonify({
                    "error": "Ghostscript compression failed",
                    "details": result.stderr.decode()
                }), 500

            with open(output_path, 'rb') as f:
                result_bytes = f.read()

        finally:
            if os.path.exists(input_path):
                os.unlink(input_path)
            if os.path.exists(output_path):
                os.unlink(output_path)

        # If Ghostscript made it bigger, return original
        if len(result_bytes) >= original_size:
            result_bytes = pdf_bytes

        response = send_file(
            io.BytesIO(result_bytes),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'foldpdf-compressed-{mode}.pdf'
        )
        response.headers['X-Original-Size'] = str(original_size)
        response.headers['X-New-Size'] = str(len(result_bytes))
        response.headers['X-Reduction'] = str(round((1 - len(result_bytes) / original_size) * 100, 1))
        return response

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Compression timed out. Try a smaller file."}), 504

    except Exception as e:
        return jsonify({
            "error": str(e),
            "details": traceback.format_exc()
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
