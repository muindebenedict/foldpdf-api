import io
import logging
import math
import os
import shutil
import subprocess
import tempfile
import time

import requests
from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
from flask_limiter import Limiter

app = Flask(__name__)

MAX_UPLOAD_MB = 50
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

DEFAULT_ALLOWED_ORIGINS = ",".join([
    "https://www.foldpdf.online",
    "https://foldpdf.online",
    "http://localhost:3000",
    "http://localhost:4173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:4173",
])
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS).split(",")
    if origin.strip()
]

CORS(app, origins=ALLOWED_ORIGINS, expose_headers=["X-Converted-By", "Retry-After", "X-Original-Size", "X-Compressed-Size", "X-Target-Met"])

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

# Optional backup converter, used only when Adobe's free monthly quota is used up.
COMPDF_API_URL = "https://api-server.compdf.com/server/v2/process/"


def error_response(message, code, status):
    return jsonify({"error": message, "code": code}), status


@app.before_request
def only_foldpdf_can_convert():
    # Browsers always send Origin on these cross-site POSTs. Health checks (GET) stay open for Uptime Robot.
    if request.method == "POST" and request.path.startswith("/api/"):
        if request.headers.get("Origin") not in ALLOWED_ORIGINS:
            return error_response("This service only accepts requests from FoldPDF.", "FORBIDDEN_ORIGIN", 403)


def client_ip():
    # Render sits behind Cloudflare, which sets CF-Connecting-IP to the real visitor address.
    for header in ("CF-Connecting-IP", "True-Client-IP"):
        value = request.headers.get(header)
        if value:
            return value.strip()
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


# In-memory counters are fine: gunicorn runs a single worker. They reset when the server restarts.
limiter = Limiter(client_ip, app=app, storage_uri="memory://", headers_enabled=True)

# PDF→Word, PDF→PowerPoint and Word→PDF share one budget, because they all use the Adobe quota.
adobe_limit = limiter.shared_limit("10 per hour;30 per day", scope="adobe")


@app.errorhandler(413)
def file_too_large(e):
    return error_response(f"File too large. Maximum size is {MAX_UPLOAD_MB}MB.", "FILE_TOO_LARGE", 413)


@app.errorhandler(429)
def rate_limited(e):
    body = {"error": "Too many conversions from your network. Please try again later.", "code": "RATE_LIMITED"}
    current = limiter.current_limit
    if current is not None:
        body["retry_after"] = max(1, math.ceil(current.reset_at - time.time()))
    return jsonify(body), 429


def uploaded_file():
    if "file" not in request.files:
        return None, error_response("No file uploaded", "BAD_REQUEST", 400)
    file = request.files["file"]
    if not file or file.filename == "":
        return None, error_response("No file selected", "BAD_REQUEST", 400)
    return file, None


class QuotaExceeded(Exception):
    """Adobe's free monthly conversions are used up (or Adobe is rate-limiting us)."""


class ComPDFError(Exception):
    pass


def adobe_convert(data, media_type, make_job, result_cls):
    from adobe.pdfservices.operation.auth.service_principal_credentials import ServicePrincipalCredentials
    from adobe.pdfservices.operation.exception.exceptions import ServiceUsageException
    from adobe.pdfservices.operation.pdf_services import PDFServices

    credentials = ServicePrincipalCredentials(
        client_id=os.environ.get("ADOBE_CLIENT_ID"),
        client_secret=os.environ.get("ADOBE_CLIENT_SECRET")
    )
    pdf_services = PDFServices(credentials=credentials)

    input_asset = None
    result_asset = None
    try:
        input_asset = pdf_services.upload(input_stream=data, mime_type=media_type)
        location = pdf_services.submit(make_job(input_asset))
        pdf_services_response = pdf_services.get_job_result(location, result_cls)
        result_asset = pdf_services_response.get_result().get_asset()
        return pdf_services.get_content(result_asset).get_input_stream()
    except ServiceUsageException as e:
        logging.warning("Adobe usage limit reached: %s", e.error_code)
        raise QuotaExceeded() from e
    finally:
        # Adobe keeps uploaded and generated files for 24 hours unless we delete them.
        for asset in (input_asset, result_asset):
            if asset is None:
                continue
            try:
                pdf_services.delete_asset(asset)
            except Exception:
                logging.exception("Could not delete an Adobe asset")


def compdf_convert(data, filename, conversion):
    # ComPDF deletes the files when the request finishes.
    response = requests.post(
        COMPDF_API_URL + conversion,
        headers={"x-api-key": os.environ["COMPDF_API_KEY"], "Accept": "application/json"},
        files={"file": (filename, data)},
        data={"language": "1"},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    if str(payload.get("code")) != "200":
        raise ComPDFError(f"ComPDF error {payload.get('code')}: {payload.get('msg')}")

    files = (payload.get("data") or {}).get("fileInfoDTOList") or []
    if not files or files[0].get("status") != "success" or not files[0].get("downloadUrl"):
        raise ComPDFError("ComPDF did not return a converted file")

    download = requests.get(files[0]["downloadUrl"], timeout=30)
    download.raise_for_status()
    return download.content


def convert_with_fallback(data, filename, media_type, make_job, result_cls, compdf_conversion):
    try:
        return adobe_convert(data, media_type, make_job, result_cls), "adobe"
    except QuotaExceeded:
        if not (os.environ.get("COMPDF_API_KEY") and compdf_conversion):
            raise
        try:
            return compdf_convert(data, filename, compdf_conversion), "compdf"
        except Exception:
            logging.exception("ComPDF backup conversion failed")
            raise QuotaExceeded()


def run_conversion(media_type, make_job, result_cls, compdf_conversion, mimetype, download_name):
    file, error = uploaded_file()
    if error:
        return error

    try:
        output, converted_by = convert_with_fallback(
            file.read(), file.filename, media_type, make_job, result_cls, compdf_conversion
        )
    except QuotaExceeded:
        return error_response(
            "This converter has used all its free conversions for this month. Please try again next month.",
            "QUOTA_EXCEEDED",
            503,
        )
    except Exception:
        logging.exception("Conversion failed")
        return error_response("Conversion failed. Please try again.", "CONVERSION_FAILED", 500)

    response = send_file(io.BytesIO(output), mimetype=mimetype, as_attachment=True, download_name=download_name)
    response.headers["X-Converted-By"] = converted_by
    return response


# Fixed levels (unchanged) and the target-size search, gentlest settings first.
COMPRESSION_LEVELS = {
    "ultra": ("/screen", 72),
    "quality": ("/printer", 150),
    "smart": ("/ebook", 100),
}
# Tried in order from gentlest to strongest when a target size is asked for. 50 DPI is the floor:
# below it, text in scanned pages stops being readable.
TARGET_STEPS = [("/printer", 150), ("/ebook", 120), ("/ebook", 100), ("/screen", 85), ("/screen", 72), ("/screen", 60), ("/screen", 50)]
TARGET_TIME_BUDGET_SECONDS = 90  # stays under gunicorn's 120 s worker timeout


def run_ghostscript(input_path, output_path, pdf_settings, dpi):
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
        raise RuntimeError("Ghostscript failed")
    return os.path.getsize(output_path)


def compress_to_target(input_path, temp_dir, target_bytes):
    """Binary-search TARGET_STEPS for the gentlest settings that fit. Returns (path, met_target)."""
    deadline = time.monotonic() + TARGET_TIME_BUDGET_SECONDS
    sizes = {}

    def attempt(index):
        if index not in sizes:
            out = os.path.join(temp_dir, f"try-{index}.pdf")
            sizes[index] = (run_ghostscript(input_path, out, *TARGET_STEPS[index]), out)
        return sizes[index]

    low, high, best = 0, len(TARGET_STEPS) - 1, None
    while low <= high and time.monotonic() < deadline:
        mid = (low + high) // 2
        size, path = attempt(mid)
        if size <= target_bytes:
            best, high = path, mid - 1
        else:
            low = mid + 1

    if best:
        return best, True
    # Nothing fitted: hand back the smallest readable result we produced.
    smallest = min(sizes.values(), key=lambda item: item[0])
    return smallest[1], False


@app.route("/api/compress", methods=["POST"])
@limiter.limit("30 per hour")
def compress():
    file, error = uploaded_file()
    if error:
        return error

    level = request.form.get("mode", "smart")
    target_bytes = None
    if level == "target":
        try:
            target_kb = int(request.form.get("target_kb", "100"))
        except ValueError:
            return error_response("Choose a target size in KB.", "BAD_REQUEST", 400)
        if not 20 <= target_kb <= 20480:
            return error_response("Choose a target size between 20 KB and 20 MB.", "BAD_REQUEST", 400)
        target_bytes = target_kb * 1024

    temp_dir = tempfile.mkdtemp()
    input_path = os.path.join(temp_dir, "input.pdf")
    output_path = os.path.join(temp_dir, "output.pdf")

    try:
        file.save(input_path)
        original_size = os.path.getsize(input_path)
        target_met = None

        if target_bytes is not None and original_size <= target_bytes:
            # Already small enough: return it untouched rather than risk making it bigger.
            output_path, target_met = input_path, True
        elif target_bytes is not None:
            output_path, target_met = compress_to_target(input_path, temp_dir, target_bytes)
        else:
            run_ghostscript(input_path, output_path, *COMPRESSION_LEVELS.get(level, COMPRESSION_LEVELS["smart"]))

        compressed_size = os.path.getsize(output_path)
        with open(output_path, "rb") as f:
            compressed_data = f.read()

        response = send_file(
            io.BytesIO(compressed_data),
            mimetype="application/pdf",
            as_attachment=True,
            download_name="compressed.pdf"
        )
        response.headers["X-Original-Size"] = str(original_size)
        response.headers["X-Compressed-Size"] = str(compressed_size)
        if target_met is not None:
            response.headers["X-Target-Met"] = "true" if target_met else "false"
        return response

    except subprocess.TimeoutExpired:
        return error_response("Compression timed out", "TIMEOUT", 500)
    except Exception:
        logging.exception("Compression failed")
        return error_response("Compression failed", "CONVERSION_FAILED", 500)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@app.route("/api/convert-to-word", methods=["POST"])
@adobe_limit
def convert_to_word():
    from adobe.pdfservices.operation.pdf_services_media_type import PDFServicesMediaType
    from adobe.pdfservices.operation.pdfjobs.jobs.export_pdf_job import ExportPDFJob
    from adobe.pdfservices.operation.pdfjobs.params.export_pdf.export_pdf_params import ExportPDFParams
    from adobe.pdfservices.operation.pdfjobs.params.export_pdf.export_pdf_target_format import ExportPDFTargetFormat
    from adobe.pdfservices.operation.pdfjobs.result.export_pdf_result import ExportPDFResult

    return run_conversion(
        PDFServicesMediaType.PDF,
        lambda asset: ExportPDFJob(
            input_asset=asset,
            export_pdf_params=ExportPDFParams(target_format=ExportPDFTargetFormat.DOCX)
        ),
        ExportPDFResult,
        "pdf/docx",
        DOCX_MIME,
        "converted.docx",
    )


@app.route("/api/convert-to-ppt", methods=["POST"])
@adobe_limit
def convert_to_ppt():
    from adobe.pdfservices.operation.pdf_services_media_type import PDFServicesMediaType
    from adobe.pdfservices.operation.pdfjobs.jobs.export_pdf_job import ExportPDFJob
    from adobe.pdfservices.operation.pdfjobs.params.export_pdf.export_pdf_params import ExportPDFParams
    from adobe.pdfservices.operation.pdfjobs.params.export_pdf.export_pdf_target_format import ExportPDFTargetFormat
    from adobe.pdfservices.operation.pdfjobs.result.export_pdf_result import ExportPDFResult

    return run_conversion(
        PDFServicesMediaType.PDF,
        lambda asset: ExportPDFJob(
            input_asset=asset,
            export_pdf_params=ExportPDFParams(target_format=ExportPDFTargetFormat.PPTX)
        ),
        ExportPDFResult,
        "pdf/pptx",
        PPTX_MIME,
        "converted.pptx",
    )


@app.route("/api/convert-word-to-pdf", methods=["POST"])
@adobe_limit
def convert_word_to_pdf():
    from adobe.pdfservices.operation.pdf_services_media_type import PDFServicesMediaType
    from adobe.pdfservices.operation.pdfjobs.jobs.create_pdf_job import CreatePDFJob
    from adobe.pdfservices.operation.pdfjobs.result.create_pdf_result import CreatePDFResult

    file = request.files.get("file")
    extension = os.path.splitext(file.filename)[1].lower() if file and file.filename else ""
    if extension not in (".docx", ".doc"):
        return error_response("Please upload a Word document (.docx or .doc).", "BAD_REQUEST", 400)

    return run_conversion(
        PDFServicesMediaType.DOCX if extension == ".docx" else PDFServicesMediaType.DOC,
        lambda asset: CreatePDFJob(input_asset=asset),
        CreatePDFResult,
        "docx/pdf" if extension == ".docx" else None,
        "application/pdf",
        "converted.pdf",
    )


@app.route("/api/convert-to-pdf", methods=["POST"])
@limiter.limit("30 per hour")
def convert_to_pdf():
    file, error = uploaded_file()
    if error:
        return error

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
            return error_response("Conversion failed. Please try again.", "CONVERSION_FAILED", 500)

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
        return error_response("Conversion timed out", "TIMEOUT", 500)
    except Exception:
        logging.exception("PowerPoint conversion failed")
        return error_response("Conversion failed. Please try again.", "CONVERSION_FAILED", 500)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@app.route("/api/health", methods=["GET"])
@limiter.exempt
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
