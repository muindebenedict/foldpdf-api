import io
import os
import shutil
import subprocess
import tempfile
import json
import logging
from datetime import datetime
from flask import Flask, request, send_file, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route("/api/compress", methods=["POST"])
def compress():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    file = request.files["file"]
    level = request.form.get("mode", "smart")
    
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
        else:
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
    output_docx_path = os.path.join(temp_dir, "output.docx")

    try:
        file.save(input_pdf_path)

        from adobe.pdfservices.operation.auth.service_principal_credentials import ServicePrincipalCredentials
        from adobe.pdfservices.operation.pdf_services import PDFServices
        from adobe.pdfservices.operation.pdf_services_media_type import PDFServicesMediaType
        from adobe.pdfservices.operation.io.cloud_asset import CloudAsset
        from adobe.pdfservices.operation.io.stream_asset import StreamAsset
        from adobe.pdfservices.operation.pdfjobs.jobs.export_pdf_job import ExportPDFJob
        from adobe.pdfservices.operation.pdfjobs.params.export_pdf.export_pdf_params import ExportPDFParams
        from adobe.pdfservices.operation.pdfjobs.params.export_pdf.export_pdf_target_format import ExportPDFTargetFormat
        from adobe.pdfservices.operation.pdfjobs.result.export_pdf_result import ExportPDFResult

        credentials = ServicePrincipalCredentials(
            client_id=os.environ.get("ADOBE_CLIENT_ID"),
            client_secret=os.environ.get("ADOBE_CLIENT_SECRET")
        )

        pdf_services = PDFServices(credentials=credentials)

        with open(input_pdf_path, "rb") as f:
            input_stream = f.read()

        input_asset = pdf_services.upload(
            input_stream=input_stream,
            mime_type=PDFServicesMediaType.PDF
        )

        export_params = ExportPDFParams(
            target_format=ExportPDFTargetFormat.DOCX
        )

        export_job = ExportPDFJob(
            input_asset=input_asset,
            export_pdf_params=export_params
        )

        location = pdf_services.submit(export_job)
        pdf_services_response = pdf_services.get_job_result(
            location,
            ExportPDFResult
        )

        result_asset: CloudAsset = pdf_services_response.get_result().get_asset()
        stream_asset: StreamAsset = pdf_services.get_content(result_asset)

        with open(output_docx_path, "wb") as f:
            f.write(stream_asset.get_input_stream())

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

    except Exception as e:
        return jsonify({"error": "Conversion failed. Please try again."}), 500
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@app.route("/api/convert-to-ppt", methods=["POST"])
def convert_to_ppt():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if not file or file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    temp_dir = tempfile.mkdtemp()
    input_pdf_path = os.path.join(temp_dir, "input.pdf")
    output_pptx_path = os.path.join(temp_dir, "output.pptx")

    try:
        file.save(input_pdf_path)

        from adobe.pdfservices.operation.auth.service_principal_credentials import ServicePrincipalCredentials
        from adobe.pdfservices.operation.pdf_services import PDFServices
        from adobe.pdfservices.operation.pdf_services_media_type import PDFServicesMediaType
        from adobe.pdfservices.operation.io.cloud_asset import CloudAsset
        from adobe.pdfservices.operation.io.stream_asset import StreamAsset
        from adobe.pdfservices.operation.pdfjobs.jobs.export_pdf_job import ExportPDFJob
        from adobe.pdfservices.operation.pdfjobs.params.export_pdf.export_pdf_params import ExportPDFParams
        from adobe.pdfservices.operation.pdfjobs.params.export_pdf.export_pdf_target_format import ExportPDFTargetFormat
        from adobe.pdfservices.operation.pdfjobs.result.export_pdf_result import ExportPDFResult

        credentials = ServicePrincipalCredentials(
            client_id=os.environ.get("ADOBE_CLIENT_ID"),
            client_secret=os.environ.get("ADOBE_CLIENT_SECRET")
        )

        pdf_services = PDFServices(credentials=credentials)

        with open(input_pdf_path, "rb") as f:
            input_stream = f.read()

        input_asset = pdf_services.upload(
            input_stream=input_stream,
            mime_type=PDFServicesMediaType.PDF
        )

        export_params = ExportPDFParams(
            target_format=ExportPDFTargetFormat.PPTX
        )

        export_job = ExportPDFJob(
            input_asset=input_asset,
            export_pdf_params=export_params
        )

        location = pdf_services.submit(export_job)
        pdf_services_response = pdf_services.get_job_result(
            location,
            ExportPDFResult
        )

        result_asset: CloudAsset = pdf_services_response.get_result().get_asset()
        stream_asset: StreamAsset = pdf_services.get_content(result_asset)

        with open(output_pptx_path, "wb") as f:
            f.write(stream_asset.get_input_stream())

        if not os.path.exists(output_pptx_path):
            return jsonify({"error": "Conversion failed. Please try again."}), 500

        with open(output_pptx_path, "rb") as f:
            pptx_data = f.read()

        file_stream = io.BytesIO(pptx_data)
        file_stream.seek(0)

        return send_file(
            file_stream,
            mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            as_attachment=True,
            download_name="converted.pptx"
        )

    except Exception as e:
        return jsonify({"error": "Conversion failed. Please try again."}), 500
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@app.route("/api/convert-to-pdf", methods=["POST"])
def convert_to_pdf():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if not file or file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    temp_dir = tempfile.mkdtemp()
    input_pptx_path = os.path.join(temp_dir, "input.pptx")
    output_pdf_path = os.path.join(temp_dir, "input.pdf")

    try:
        file.save(input_pptx_path)

        result = subprocess.run([
            "libreoffice",
            "--headless",
            "--convert-to", "pdf",
            "--outdir", temp_dir,
            input_pptx_path
        ], capture_output=True, timeout=60)

        if result.returncode != 0 or not os.path.exists(output_pdf_path):
            return jsonify({"error": "Conversion failed. Please try again."}), 500

        with open(output_pdf_path, "rb") as f:
            pdf_data = f.read()

        file_stream = io.BytesIO(pdf_data)
        file_stream.seek(0)

        return send_file(
            file_stream,
            mimetype="application/pdf",
            as_attachment=True,
            download_name="converted.pdf"
        )

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Conversion timed out"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/api/fireflies-webhook", methods=["POST"])
def fireflies_webhook():
    try:
        payload = request.get_json(force=True, silent=True)

        logging.info(f"[Fireflies Webhook] Received at {datetime.utcnow()}: {json.dumps(payload)}")

        with open("fireflies_webhook_log.jsonl", "a") as f:
            f.write(json.dumps({"received_at": str(datetime.utcnow()), "payload": payload}) + "\n")

        return jsonify({"status": "received"}), 200

    except Exception as e:
        logging.error(f"[Fireflies Webhook] Error: {e}")
        return jsonify({"status": "error logged"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
