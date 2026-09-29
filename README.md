# FoldPDF API

Backend API for [FoldPDF](https://www.foldpdf.online) — a free, privacy-first PDF toolkit.

## What this API does

This Flask server handles PDF processing for FoldPDF tools that require server-side processing:

- **Compress PDF** (`/api/compress`) — three compression levels using Ghostscript
- **PDF to Word** (`/api/convert-to-word`) — high quality conversion using Adobe PDF Services API
- **PDF to PowerPoint** (`/api/convert-to-ppt`) — conversion using Adobe PDF Services API
- **Word to PDF** (`/api/convert-word-to-pdf`) — `.docx` and `.doc` using Adobe PDF Services API
- **PowerPoint to PDF** (`/api/convert-to-pdf`) — conversion using LibreOffice

All other FoldPDF tools run entirely in the browser with no server involvement.

`GET /api/health` returns `{"status": "ok"}` and is used by the uptime monitor that keeps the Render service awake.

## Tech Stack

- Python Flask
- Ghostscript for compression
- Adobe PDF Services API for document conversion (ComPDF as an optional backup)
- LibreOffice for PowerPoint to PDF
- Deployed on Render

## Environment variables

| Name | Required | Purpose |
|---|---|---|
| `ADOBE_CLIENT_ID`, `ADOBE_CLIENT_SECRET` | Yes | Adobe PDF Services credentials |
| `COMPDF_API_KEY` | No | ComPDF public key. When set, ComPDF is used only after Adobe's free monthly quota is used up |
| `ALLOWED_ORIGINS` | No | Comma-separated list of sites allowed to call the API. Defaults to foldpdf.online (with and without `www`) and `localhost`/`127.0.0.1` on ports 3000 and 4173 |

## Limits

- Uploads are limited to 50 MB.
- Conversion requests (POST) are only accepted from the allowed origins.
- Per visitor IP: the three Adobe conversions share 10 per hour and 30 per day; Compress and PowerPoint to PDF allow 30 per hour each.
- Errors are JSON: `{"error": "...", "code": "..."}`. Codes: `BAD_REQUEST`, `FORBIDDEN_ORIGIN`, `FILE_TOO_LARGE`, `RATE_LIMITED` (with `retry_after` seconds), `QUOTA_EXCEEDED`, `CONVERSION_FAILED`, `TIMEOUT`.
- Successful Adobe/ComPDF conversions include an `X-Converted-By: adobe|compdf` header.

## Privacy

Files are processed in memory or in a temporary folder and deleted as soon as the response is sent. Nothing is stored or logged.

For the Adobe conversions, the uploaded file and the converted result are deleted from Adobe's storage right after the conversion (Adobe would otherwise keep them for 24 hours). ComPDF deletes files when the request finishes.

## Live Site

[https://www.foldpdf.online](https://www.foldpdf.online)
