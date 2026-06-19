# FoldPDF API

Backend API for [FoldPDF](https://www.foldpdf.online) — a free, privacy-first PDF toolkit.

## What this API does

This Flask server handles PDF processing for FoldPDF tools that require server-side processing:

- **Compress PDF** — three compression levels using Ghostscript
- **PDF to Word** — high quality conversion using Adobe PDF Services API
- **PDF to PowerPoint** — conversion using Adobe PDF Services API  
- **PowerPoint to PDF** — conversion using LibreOffice

All other FoldPDF tools run entirely in the browser with no server involvement.

## Tech Stack

- Python Flask
- Ghostscript for compression
- Adobe PDF Services API for document conversion
- LibreOffice for PowerPoint to PDF
- Deployed on Render

## Privacy

Files sent to this API are deleted immediately after the user downloads their result. Nothing is stored or logged.

## Live Site

[https://www.foldpdf.online](https://www.foldpdf.online)
