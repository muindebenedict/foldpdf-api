import io
import os
import shutil
import subprocess
import tempfile
from flask import Flask, request, send_file, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route("/api/compress", methods=["POST"])
def compress():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    file = request.files["file"]
    level = request.form.get("level", "smart")
    
    if not file or file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    temp_dir = tempfile.mkdtemp()
    input_path = os.path.join(temp_dir, "input.pdf")
    output_path = os.path.join(temp_dir, "output.pdf")

    try:
        file.save(input_path)
        
        if level == "ultra":
            pdf_settings = "/screen"
            dpi = 72
        elif level == "quality":
            pdf_settings = "/printer"
            dpi = 150
        else:  # smart
            pdf_settings = "/ebook"
            dpi = 100

        result = subprocess.run([
            "gs",
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.4",
            f"-dPDFSETTINGS={pdf_settings}",
            f"-dColorImageResolution={dpi}",
            f"-dGrayImageResolution={dpi}",
            f"-dMonoImageResolution={dpi}",
            "-dNOPAUSE",
            "-dQUIET",
            "-dBATCH",
            f"-sOutputFile={output_path}",
            input_path
        ], capture_output=True, timeout=60)

        if result.returncode != 0 or not os.path.exists(output_path):
            return jsonify({"error": "Compression failed"}), 500

        original_size = os.path.getsize(input_path)
        compressed_size = os.path.getsize(output_path)

        with open(output_path, "rb") as f:
            compressed_data = f.read()

        file_stream = io.BytesIO(compressed_data)
        file_stream.seek(0)

        response = send_file(
            file_stream,
            mimetype="application/pdf",
            as_attachment=True,
            download_name="compressed.pdf"
        )
        response.headers["X-Original-Size"] = str(original_size)
        response.headers["X-Compressed-Size"] = str(compressed_size)
        return response

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Compression timed out"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@app.route("/api/convert-to-word", methods=["POST"])
def convert_to_word():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if not file or file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    temp_dir = tempfile.mkdtemp()
    input_pdf_path = os.path.join(temp_dir, "input.pdf")

    try:
        file.save(input_pdf_path)

        result = subprocess.run([
            "libreoffice", "--headless", "--convert-to", "docx",
            "--outdir", temp_dir, input_pdf_path
        ], capture_output=True, text=True, timeout=120)

        if result.returncode != 0:
            return jsonify({"error": "Conversion failed. Please try again."}), 500

        output_docx_path = os.path.join(temp_dir, "input.docx")

        if not os.path.exists(output_docx_path):
            return jsonify({"error": "Conversion failed. Please try again."}), 500

        with open(output_docx_path, "rb") as f:
            docx_data = f.read()

        file_stream = io.BytesIO(docx_data)
        file_stream.seek(0)

        return send_file(
            file_stream,
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            as_attachment=True,
            download_name="converted.docx"
        )

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Conversion timed out. Please try a smaller file."}), 500
    except Exception as e:
        return jsonify({"error": "Conversion failed. Please try again."}), 500
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
