"""
report_pdf.py

Genera el reporte de seguridad como PDF real, en el servidor — sin pasar
por el navegador del usuario. Reemplaza el intento anterior (html2pdf.js
en el navegador), que falló de tres formas distintas porque "fotografiaba"
la página en vez de generar el PDF directamente.

Usa xhtml2pdf, que es Python puro (sin dependencias del sistema como
Pango/Cairo) — esto importa porque Render, a diferencia de tu computadora,
no necesariamente tiene esas librerías instaladas, y una dependencia que
falla en producción pero funciona en local es exactamente el tipo de
sorpresa que ya vivimos antes con otros bugs.
"""

import io
import html as html_lib
from xhtml2pdf import pisa

TB_NAVY = "#0f2a4a"
TB_GOLD = "#a8842c"
TB_GOLD_BG = "#fdf8ec"
TB_TEXT = "#1f2937"
TB_TEXT_DIM = "#64748b"
TB_BORDER = "#e2e8f0"
TB_CRITICAL = "#9a3412"
TB_CRITICAL_BG = "#fef2f2"

# El mismo logo (escudo + candado) usado en el sitio, incrustado en
# base64 — nunca depende de cargar una imagen externa.
with open("tb_logo_base64.txt", "r") as _f:
    TB_LOGO_BASE64 = _f.read().strip()


def _esc(s) -> str:
    """Escapa texto para HTML de forma segura, tolerando None."""
    return html_lib.escape(str(s)) if s is not None else ""


def _severity_style(sev: str) -> str:
    if (sev or "").upper() == "CRITICAL":
        return f"background-color:{TB_CRITICAL_BG}; color:{TB_CRITICAL}; border:1px solid #fecaca;"
    return f"background-color:{TB_GOLD_BG}; color:{TB_GOLD}; border:1px solid #f0e2bb;"


def build_report_html(report_id: str, project_url: str, overall_severity: str,
                       overall_summary: str, findings: list, generated_at: str,
                       payment_line: str) -> str:
    """Arma el HTML completo del reporte (fondo blanco, azul/dorado
    corporativos) — este mismo HTML se usa tanto para la página web del
    reporte como insumo para generar el PDF.
    """
    findings_html = ""
    for i, f in enumerate(findings or []):
        finding_id = f"{report_id}-{str(i + 1).zfill(2)}"
        table = _esc(f.get("table", ""))
        severity = _esc(f.get("severity") or overall_severity or "")
        plain_explanation = _esc(f.get("plain_explanation", ""))
        business_impact = _esc(f.get("business_impact", ""))
        compliance_note = f.get("compliance_note")
        sql_fix = _esc(f.get("sql_fix", ""))

        compliance_block = ""
        if compliance_note:
            compliance_block = f"""
            <div style="border-left:3px solid {TB_GOLD}; background-color:{TB_GOLD_BG}; padding:9px 13px; margin-bottom:12px;">
              <div style="font-weight:bold; font-size:9.5px; color:{TB_GOLD}; margin-bottom:3px;">COMPLIANCE</div>
              <div style="font-size:11.5px; color:{TB_TEXT};">{_esc(compliance_note)}</div>
            </div>"""

        findings_html += f"""
        <div style="border:1px solid {TB_BORDER}; padding:16px 18px; margin-bottom:14px;">
          <table style="width:100%;"><tr>
            <td style="font-size:14px; font-weight:bold; color:{TB_NAVY};">
              {table} <span style="font-weight:normal; font-size:10.5px; color:#94a3b8;">({finding_id})</span>
            </td>
            <td align="right">
              <span style="font-size:10px; font-weight:bold; padding:3px 9px; {_severity_style(severity)}">{severity}</span>
            </td>
          </tr></table>
          <p style="font-size:12px; line-height:1.65; color:{TB_TEXT};">{plain_explanation}</p>
          <div style="border-left:3px solid {TB_NAVY}; background-color:#f8fafc; padding:9px 13px; margin-bottom:10px;">
            <div style="font-weight:bold; font-size:9.5px; color:{TB_NAVY}; margin-bottom:3px;">BUSINESS IMPACT</div>
            <div style="font-size:11.5px; color:{TB_TEXT};">{business_impact}</div>
          </div>
          {compliance_block}
          <div style="background-color:#f1f5f9; border:1px solid {TB_BORDER}; padding:11px 13px; font-family:Courier,monospace; font-size:10px; color:#1e293b;">{sql_fix}</div>
        </div>
        """

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  @page {{ size: A4; margin: 1.6cm; }}
  body {{ font-family: Helvetica, Arial, sans-serif; color: {TB_TEXT}; }}
</style>
</head>
<body>
  <table style="width:100%; border-bottom:3px solid {TB_GOLD}; padding-bottom:14px; margin-bottom:22px;">
    <tr>
      <td style="width:50px;"><img src="data:image/jpeg;base64,{TB_LOGO_BASE64}" width="38" height="38"/></td>
      <td>
        <div style="font-size:22px; font-weight:bold; color:{TB_NAVY};">TrustBoost</div>
        <div style="font-size:10px; color:{TB_GOLD}; font-weight:bold;">FREE SECURITY SCAN</div>
      </td>
      <td align="right" style="font-size:10.5px; color:{TB_TEXT_DIM};">
        Report {_esc(report_id)}<br/>{_esc(project_url)}<br/>Generated {_esc(generated_at)}
      </td>
    </tr>
  </table>

  <div style="display:inline-block; font-size:10.5px; font-weight:bold; padding:5px 13px; margin-bottom:16px; {_severity_style(overall_severity)}">
    SEVERITY: {_esc(overall_severity)}
  </div>

  <p style="font-size:12.5px; line-height:1.7; color:{TB_TEXT};">{_esc(overall_summary)}</p>

  {findings_html}

  <table style="width:100%; border-top:1px solid {TB_BORDER}; margin-top:24px; padding-top:12px;">
    <tr>
      <td style="font-size:9.5px; color:#94a3b8;">TrustBoost — generated automatically. No data values were read by the AI model.</td>
      <td align="right" style="font-size:9.5px; color:#94a3b8;">{_esc(payment_line)}</td>
    </tr>
    <tr>
      <td colspan="2" style="font-size:9.5px; color:{TB_GOLD}; padding-top:6px;">
        Lost this file? View or re-download it anytime at: https://api.trustboost.dev/report/{_esc(report_id)}
      </td>
    </tr>
  </table>
</body>
</html>"""


def generate_pdf_bytes(html_content: str) -> bytes:
    """Convierte el HTML del reporte a PDF real, en memoria. Sin
    depender del navegador del usuario ni de ninguna librería de
    'captura de pantalla'."""
    buffer = io.BytesIO()
    pisa.CreatePDF(src=html_content, dest=buffer)
    return buffer.getvalue()
