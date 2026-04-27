"""
API para geração de Ordem de Serviço em PDF - Auto Jato TC Truck
FastAPI + ReportLab | Retorna PDF em base64 para integração com Bubble
"""

import base64
import io
import os
import tempfile
import urllib.request
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, field_validator

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.platypus import Table, TableStyle

# ─── Modelos Pydantic ────────────────────────────────────────────────

class Servico(BaseModel):
    descricao: str
    valor: float

class Foto(BaseModel):
    url: Optional[str] = None      # URL pública da imagem
    base64_data: Optional[str] = None  # Imagem em base64 (sem prefixo data:...)
    legenda: Optional[str] = None

class EmpresaInfo(BaseModel):
    nome: str = "AUTO JATO TC TRUCK LTDA"
    cnpj: str = "51667908000194"
    endereco: str = "Avenida Mitsuzo Kondo, 95 - Distrito Industrial - JUNDIAÍ - SP"
    telefone: str = "(11) 93050-1993 / (11) 95089-6893"
    logo_url: Optional[str] = None
    logo_base64: Optional[str] = None

class OrdemServico(BaseModel):
    numero_os: str
    cnpj_cliente: str = ""
    razao_social: str = ""
    placa_cavalo: str = ""
    placa_carreta: Optional[str] = ""
    data_realizacao: str = ""
    latitude: Optional[str] = ""
    longitude: Optional[str] = ""
    fotos: Optional[list[Foto]] = []
    servicos: Optional[list[Servico]] = []
    empresa: Optional[EmpresaInfo] = None

    @field_validator("fotos", mode="before")
    @classmethod
    def fotos_nunca_none(cls, v):
        if v is None:
            return []
        return v

    @field_validator("servicos", mode="before")
    @classmethod
    def servicos_nunca_none(cls, v):
        if v is None:
            return []
        return v

    @field_validator("placa_carreta", "latitude", "longitude", "cnpj_cliente",
                     "razao_social", "placa_cavalo", "data_realizacao", mode="before")
    @classmethod
    def string_nunca_none(cls, v):
        if v is None:
            return ""
        return v


# ─── App FastAPI ─────────────────────────────────────────────────────

app = FastAPI(
    title="Gerador de OS - Auto Jato TC Truck",
    description="API para gerar PDF de Ordem de Serviço a partir de dados JSON",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Autenticação API Key ───────────────────────────────────────────

API_KEY = os.environ.get("API_KEY", "")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verificar_api_key(api_key: str = Security(api_key_header)):
    """Valida a API Key enviada no header X-API-Key."""
    if not API_KEY:
        # Se não configurou API_KEY no servidor, aceita qualquer request
        return api_key
    if api_key != API_KEY:
        raise HTTPException(status_code=401, detail="API Key inválida ou ausente")
    return api_key


# ─── Helpers ─────────────────────────────────────────────────────────

def load_image(foto: Foto) -> Optional[ImageReader]:
    """Carrega imagem de URL ou base64 e retorna ImageReader."""
    try:
        if foto.base64_data:
            img_data = base64.b64decode(foto.base64_data)
            return ImageReader(io.BytesIO(img_data))
        elif foto.url:
            req = urllib.request.Request(foto.url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                img_data = resp.read()
            return ImageReader(io.BytesIO(img_data))
    except Exception as e:
        print(f"Erro ao carregar imagem: {e}")
    return None


def load_logo(empresa: EmpresaInfo) -> Optional[ImageReader]:
    """Carrega logo da empresa de URL ou base64."""
    try:
        if empresa.logo_base64:
            img_data = base64.b64decode(empresa.logo_base64)
            return ImageReader(io.BytesIO(img_data))
        elif empresa.logo_url:
            req = urllib.request.Request(empresa.logo_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                img_data = resp.read()
            return ImageReader(io.BytesIO(img_data))
    except Exception as e:
        print(f"Erro ao carregar logo: {e}")
    return None


def formatar_valor(valor: float) -> str:
    """Formata valor em reais: R$1.234,56"""
    return f"R${valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def draw_rounded_rect(c: canvas.Canvas, x, y, w, h, radius=8, stroke=True, fill=False):
    """Desenha retângulo com bordas arredondadas."""
    c.roundRect(x, y, w, h, radius, stroke=int(stroke), fill=int(fill))


def draw_icon_clipboard(c, cx, cy, size=10):
    """Desenha ícone de prancheta (Ordem de Serviço)."""
    s = size
    c.setStrokeColor(colors.Color(0.45, 0.45, 0.45))
    c.setFillColor(colors.Color(0.45, 0.45, 0.45))
    c.setLineWidth(1.2)
    # Corpo da prancheta
    c.roundRect(cx - s*0.4, cy - s*0.5, s*0.8, s, 1.5, stroke=1, fill=0)
    # Clip no topo
    c.roundRect(cx - s*0.2, cy + s*0.35, s*0.4, s*0.25, 1, stroke=1, fill=1)
    # Linhas de texto
    c.setLineWidth(0.8)
    for i in range(3):
        ly = cy + s*0.15 - i * s*0.25
        c.line(cx - s*0.25, ly, cx + s*0.25, ly)


def draw_icon_camera(c, cx, cy, size=10):
    """Desenha ícone de câmera (Fotos)."""
    s = size
    c.setStrokeColor(colors.Color(0.45, 0.45, 0.45))
    c.setFillColor(colors.Color(0.45, 0.45, 0.45))
    c.setLineWidth(1.2)
    # Corpo da câmera
    c.roundRect(cx - s*0.5, cy - s*0.35, s, s*0.65, 2, stroke=1, fill=0)
    # Lente (círculo)
    c.circle(cx, cy - s*0.05, s*0.2, stroke=1, fill=0)
    # Flash no topo
    c.setLineWidth(0.8)
    c.line(cx - s*0.15, cy + s*0.3, cx + s*0.15, cy + s*0.3)
    c.line(cx - s*0.15, cy + s*0.3, cx - s*0.15, cy + s*0.42)
    c.line(cx - s*0.15, cy + s*0.42, cx + s*0.15, cy + s*0.42)


def draw_icon_wrench(c, cx, cy, size=10):
    """Desenha ícone de checklist/serviços."""
    s = size
    c.setStrokeColor(colors.Color(0.45, 0.45, 0.45))
    c.setFillColor(colors.Color(0.45, 0.45, 0.45))
    c.setLineWidth(1.2)
    # Três checkmarks com linhas
    for i in range(3):
        ly = cy + s*0.35 - i * s*0.35
        # Check
        c.setLineWidth(1.4)
        c.line(cx - s*0.4, ly, cx - s*0.3, ly - s*0.1)
        c.line(cx - s*0.3, ly - s*0.1, cx - s*0.15, ly + s*0.1)
        # Linha de texto
        c.setLineWidth(0.8)
        c.line(cx - s*0.05, ly, cx + s*0.4, ly)


def draw_section_header(c: canvas.Canvas, x, y, w, titulo, icon_type=None):
    """Desenha cabeçalho de seção com ícone e título."""
    # Fundo cinza claro no header
    c.setFillColor(colors.Color(0.96, 0.96, 0.96))
    c.roundRect(x, y - 2, w, 28, 6, stroke=0, fill=1)

    # Ícone (quadrado cinza com ícone dentro)
    icon_x = x + 10
    icon_y = y + 2
    icon_w = 22
    icon_h = 22
    c.setFillColor(colors.Color(0.85, 0.85, 0.85))
    c.roundRect(icon_x, icon_y, icon_w, icon_h, 4, stroke=0, fill=1)

    # Desenha ícone dentro do quadrado
    icon_cx = icon_x + icon_w / 2
    icon_cy = icon_y + icon_h / 2
    c.saveState()
    if icon_type == "clipboard":
        draw_icon_clipboard(c, icon_cx, icon_cy, size=9)
    elif icon_type == "camera":
        draw_icon_camera(c, icon_cx, icon_cy, size=9)
    elif icon_type == "checklist":
        draw_icon_wrench(c, icon_cx, icon_cy, size=9)
    c.restoreState()

    # Título
    c.setFillColor(colors.Color(0.15, 0.15, 0.15))
    c.setFont("Helvetica-Bold", 11)
    c.drawString(x + 40, y + 7, titulo)


# ─── Gerador de PDF ──────────────────────────────────────────────────

def gerar_pdf(os_data: OrdemServico) -> bytes:
    """Gera o PDF da Ordem de Serviço e retorna os bytes."""

    buffer = io.BytesIO()
    width, height = A4  # 595.27 x 841.89 pontos
    c = canvas.Canvas(buffer, pagesize=A4)

    empresa = os_data.empresa or EmpresaInfo()

    # Garante que fotos e servicos nunca sejam None
    if os_data.fotos is None:
        os_data.fotos = []
    if os_data.servicos is None:
        os_data.servicos = []

    margin_x = 40
    content_w = width - 2 * margin_x
    y_cursor = height - 40  # Topo

    # ═══════════════════════════════════════════════════════════════
    # SEÇÃO 1: CABEÇALHO DA EMPRESA
    # ═══════════════════════════════════════════════════════════════
    header_h = 90
    y_cursor -= header_h

    # Borda do card
    c.setStrokeColor(colors.Color(0.85, 0.85, 0.85))
    c.setLineWidth(0.8)
    draw_rounded_rect(c, margin_x, y_cursor, content_w, header_h, radius=8)

    # Logo
    logo_img = load_logo(empresa)
    logo_x = margin_x + 15
    logo_y = y_cursor + 12
    logo_w = 90
    logo_h = 65

    if logo_img:
        try:
            c.drawImage(logo_img, logo_x, logo_y, width=logo_w, height=logo_h,
                        preserveAspectRatio=True, mask='auto')
        except:
            # Placeholder se a logo falhar
            c.setFillColor(colors.Color(0.93, 0.93, 0.93))
            c.roundRect(logo_x, logo_y, logo_w, logo_h, 6, stroke=0, fill=1)
    else:
        c.setFillColor(colors.Color(0.93, 0.93, 0.93))
        c.roundRect(logo_x, logo_y, logo_w, logo_h, 6, stroke=0, fill=1)
        c.setFillColor(colors.Color(0.6, 0.6, 0.6))
        c.setFont("Helvetica", 8)
        c.drawCentredString(logo_x + logo_w / 2, logo_y + logo_h / 2, "LOGO")

    # Informações da empresa
    info_x = margin_x + 130
    info_y = y_cursor + header_h - 28

    c.setFillColor(colors.Color(0.2, 0.2, 0.2))
    c.setFont("Helvetica-Bold", 10)
    c.drawString(info_x, info_y, f"{empresa.nome} - {empresa.cnpj}")

    c.setFont("Helvetica", 9)
    c.setFillColor(colors.Color(0.35, 0.35, 0.35))
    c.drawString(info_x, info_y - 18, empresa.endereco)
    c.drawString(info_x, info_y - 34, empresa.telefone)

    y_cursor -= 15

    # ═══════════════════════════════════════════════════════════════
    # SEÇÃO 2: ORDEM DE SERVIÇO
    # ═══════════════════════════════════════════════════════════════
    os_section_h = 105
    y_cursor -= os_section_h

    c.setStrokeColor(colors.Color(0.85, 0.85, 0.85))
    c.setLineWidth(0.8)
    draw_rounded_rect(c, margin_x, y_cursor, content_w, os_section_h, radius=8)

    # Header da seção
    draw_section_header(c, margin_x, y_cursor + os_section_h - 30, content_w,
                        f"Ordem de serviço - {os_data.numero_os}", icon_type="clipboard")

    # Campos - Coluna esquerda
    campos_y = y_cursor + os_section_h - 52
    col1_x = margin_x + 15
    col2_x = margin_x + content_w / 2 + 10

    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(colors.Color(0.2, 0.2, 0.2))
    c.drawString(col1_x, campos_y, "CNPJ Cliente: ")
    c.setFont("Helvetica", 8.5)
    c.setFillColor(colors.Color(0.4, 0.4, 0.4))
    c.drawString(col1_x + 75, campos_y, os_data.cnpj_cliente)

    campos_y -= 16
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(colors.Color(0.2, 0.2, 0.2))
    c.drawString(col1_x, campos_y, "Placa cavalo: ")
    c.setFont("Helvetica", 8.5)
    c.setFillColor(colors.Color(0.4, 0.4, 0.4))
    c.drawString(col1_x + 75, campos_y, os_data.placa_cavalo)

    campos_y -= 16
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(colors.Color(0.2, 0.2, 0.2))
    c.drawString(col1_x, campos_y, "Data realização: ")
    c.setFont("Helvetica", 8.5)
    c.setFillColor(colors.Color(0.4, 0.4, 0.4))
    c.drawString(col1_x + 85, campos_y, os_data.data_realizacao)

    # Campos - Coluna direita
    campos_y = y_cursor + os_section_h - 52
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(colors.Color(0.2, 0.2, 0.2))
    c.drawString(col2_x, campos_y, "Razão Social: ")
    c.setFont("Helvetica", 8.5)
    c.setFillColor(colors.Color(0.4, 0.4, 0.4))
    c.drawString(col2_x + 75, campos_y, os_data.razao_social)

    campos_y -= 16
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(colors.Color(0.2, 0.2, 0.2))
    c.drawString(col2_x, campos_y, "Placa carreta: ")
    c.setFont("Helvetica", 8.5)
    c.setFillColor(colors.Color(0.4, 0.4, 0.4))
    c.drawString(col2_x + 75, campos_y, os_data.placa_carreta or "")

    campos_y -= 16
    loc_text = ""
    if os_data.latitude and os_data.longitude:
        loc_text = f"lat:{os_data.latitude} , lng:{os_data.longitude}"
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(colors.Color(0.2, 0.2, 0.2))
    c.drawString(col2_x, campos_y, "Loc.: ")
    c.setFont("Helvetica", 8.5)
    c.setFillColor(colors.Color(0.4, 0.4, 0.4))
    c.drawString(col2_x + 30, campos_y, loc_text)

    y_cursor -= 15

    # ═══════════════════════════════════════════════════════════════
    # SEÇÃO 3: FOTOS REGISTRADAS
    # ═══════════════════════════════════════════════════════════════
    if os_data.fotos:
        num_fotos = len(os_data.fotos)
        fotos_per_row = 3
        foto_w = (content_w - 60) / fotos_per_row
        foto_h = foto_w * 0.7  # Proporção
        num_rows = (num_fotos + fotos_per_row - 1) // fotos_per_row
        fotos_section_h = 40 + num_rows * (foto_h + 15) + 10

        # Verifica se cabe na página
        if y_cursor - fotos_section_h < 60:
            c.showPage()
            y_cursor = height - 40

        y_cursor -= fotos_section_h

        c.setStrokeColor(colors.Color(0.85, 0.85, 0.85))
        c.setLineWidth(0.8)
        draw_rounded_rect(c, margin_x, y_cursor, content_w, fotos_section_h, radius=8)

        # Header
        draw_section_header(c, margin_x, y_cursor + fotos_section_h - 30, content_w,
                            "Fotos registradas", icon_type="camera")

        # Fotos
        for i, foto in enumerate(os_data.fotos):
            row = i // fotos_per_row
            col = i % fotos_per_row
            fx = margin_x + 20 + col * (foto_w + 10)
            fy = y_cursor + fotos_section_h - 50 - row * (foto_h + 15)

            img = load_image(foto)
            if img:
                try:
                    # Borda arredondada da foto
                    c.saveState()
                    c.setStrokeColor(colors.Color(0.88, 0.88, 0.88))
                    c.setLineWidth(0.5)
                    c.roundRect(fx - 2, fy - foto_h - 2, foto_w + 4, foto_h + 4, 6, stroke=1, fill=0)
                    c.drawImage(img, fx, fy - foto_h, width=foto_w, height=foto_h,
                                preserveAspectRatio=True, mask='auto')
                    c.restoreState()
                except Exception as e:
                    print(f"Erro ao desenhar foto {i}: {e}")
                    c.setFillColor(colors.Color(0.93, 0.93, 0.93))
                    c.roundRect(fx, fy - foto_h, foto_w, foto_h, 6, stroke=0, fill=1)
            else:
                c.setFillColor(colors.Color(0.93, 0.93, 0.93))
                c.roundRect(fx, fy - foto_h, foto_w, foto_h, 6, stroke=0, fill=1)
                c.setFillColor(colors.Color(0.6, 0.6, 0.6))
                c.setFont("Helvetica", 8)
                c.drawCentredString(fx + foto_w / 2, fy - foto_h / 2, "Foto indisponível")

        y_cursor -= 15

    # ═══════════════════════════════════════════════════════════════
    # SEÇÃO 4: SERVIÇOS REALIZADOS
    # ═══════════════════════════════════════════════════════════════
    if os_data.servicos:
        num_servicos = len(os_data.servicos)
        servicos_section_h = 45 + num_servicos * 22 + 30  # header + linhas + total

        # Verifica se cabe na página
        if y_cursor - servicos_section_h < 60:
            c.showPage()
            y_cursor = height - 40

        y_cursor -= servicos_section_h

        c.setStrokeColor(colors.Color(0.85, 0.85, 0.85))
        c.setLineWidth(0.8)
        draw_rounded_rect(c, margin_x, y_cursor, content_w, servicos_section_h, radius=8)

        # Header
        draw_section_header(c, margin_x, y_cursor + servicos_section_h - 30, content_w,
                            "Serviços realizados", icon_type="checklist")

        # Cabeçalho da tabela
        table_y = y_cursor + servicos_section_h - 50
        c.setFont("Helvetica-Bold", 8.5)
        c.setFillColor(colors.Color(0.35, 0.35, 0.35))
        c.drawString(margin_x + 20, table_y, "Descrição")
        c.drawRightString(margin_x + content_w - 20, table_y, "Valor")

        # Linha separadora
        c.setStrokeColor(colors.Color(0.9, 0.9, 0.9))
        c.setLineWidth(0.5)
        c.line(margin_x + 15, table_y - 5, margin_x + content_w - 15, table_y - 5)

        # Itens
        total = 0.0
        item_y = table_y - 22
        for servico in os_data.servicos:
            c.setFont("Helvetica", 8.5)
            c.setFillColor(colors.Color(0.3, 0.3, 0.3))
            c.drawString(margin_x + 20, item_y, servico.descricao)
            c.drawRightString(margin_x + content_w - 20, item_y, formatar_valor(servico.valor))
            total += servico.valor

            # Linha separadora leve
            c.setStrokeColor(colors.Color(0.93, 0.93, 0.93))
            c.line(margin_x + 15, item_y - 6, margin_x + content_w - 15, item_y - 6)

            item_y -= 22

        # Total
        c.setFont("Helvetica-Bold", 10)
        c.setFillColor(colors.Color(0.15, 0.15, 0.15))
        c.drawRightString(margin_x + content_w - 20, item_y, formatar_valor(total))

    # Finalizar
    c.save()
    buffer.seek(0)
    return buffer.read()


# ─── Endpoints ───────────────────────────────────────────────────────

@app.post("/gerar-os")
async def gerar_ordem_servico(os_data: OrdemServico, _key: str = Depends(verificar_api_key)):
    """
    Gera PDF da Ordem de Serviço e retorna em base64.

    O Bubble pode chamar este endpoint via API Connector,
    enviar os dados como JSON e receber o PDF codificado em base64.
    """
    try:
        pdf_bytes = gerar_pdf(os_data)
        pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")

        return JSONResponse(content={
            "success": True,
            "pdf_base64": pdf_base64,
            "filename": f"OS_{os_data.numero_os}.pdf",
            "size_bytes": len(pdf_bytes),
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao gerar PDF: {str(e)}")


@app.post("/gerar-os/download")
async def gerar_ordem_servico_download(os_data: OrdemServico, _key: str = Depends(verificar_api_key)):
    """
    Gera PDF e retorna diretamente como arquivo para download.
    Útil para testes diretos no navegador/Swagger.
    """
    try:
        pdf_bytes = gerar_pdf(os_data)
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="OS_{os_data.numero_os}.pdf"'
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao gerar PDF: {str(e)}")


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


# ─── Execução local ─────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
