import os
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle
from sqlalchemy.orm import Session
from database import SessionLocal
from models import Project

FONT_PATH = os.path.join(os.path.dirname(__file__), "fonts", "timesnewromanpsmt.ttf")

def register_fonts():
    """Регистрирует шрифты с поддержкой кириллицы."""
    if os.path.exists(FONT_PATH):
         pdfmetrics.registerFont(TTFont('timesnewromanpsmt', FONT_PATH))
    else:
         raise FileNotFoundError(f"Шрифт не найден: {FONT_PATH}")


def generate_project_pdf(project_id, filepath):
    register_fonts()  # регистрируем шрифты перед созданием PDF

    session: Session = SessionLocal()
    project = session.query(Project).filter(Project.id == project_id).first()
    if not project:
        session.close()
        raise ValueError(f"Проект с ID {project_id} не найден")

    c = canvas.Canvas(filepath, pagesize=A4)
    width, height = A4
    margin = 20 * mm
    y = height - margin
    line_height = 6 * mm

    # Используем зарегистрированный шрифт
    c.setFont("timesnewromanpsmt", 16)
    c.drawString(margin, y, f"Смета проекта: {project.name}")
    y -= line_height * 1.5

    # Общая информация
    c.setFont("timesnewromanpsmt", 12)
    c.drawString(margin, y, "Общая информация")
    y -= line_height
    c.setFont("timesnewromanpsmt", 10)
    c.drawString(margin + 5 * mm, y, f"Заказчик: {project.customer.name if project.customer else 'Не указан'}")
    y -= line_height
    c.drawString(margin + 5 * mm, y, f"Дата создания: {project.created_at.strftime('%d.%m.%Y')}")
    y -= line_height
    c.drawString(margin + 5 * mm, y, f"Статус: {project.status}")
    y -= line_height * 1.5

    # Таблица работ
    data = [["Комната", "Тип работ", "Материал", "Подрядчик", "Площадь, м²", "Затраты мат., руб", "Затраты подр., руб"]]
    total_material = 0
    total_contractor = 0
    for work in project.works:
        room = work.room_name
        work_type = work.work_type.name if work.work_type else ""
        material = work.material.name if work.material else ""
        contractor = work.contractor.name if work.contractor else ""
        area = f"{work.area:.2f}"
        mat_cost = f"{work.material_cost:.2f}"
        cont_cost = f"{work.contractor_cost:.2f}"
        data.append([room, work_type, material, contractor, area, mat_cost, cont_cost])
        total_material += work.material_cost
        total_contractor += work.contractor_cost

    # Указываем шрифт для таблицы (можно использовать обычный)
    table = Table(data, colWidths=[30 * mm, 35 * mm, 35 * mm, 35 * mm, 20 * mm, 25 * mm, 25 * mm])
    table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'timesnewromanpsmt'),  # основной шрифт
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ALIGN', (4, 0), (-1, -1), 'RIGHT'),
        ('ALIGN', (0, 0), (3, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('FONTNAME', (0, 0), (-1, 0), 'timesnewromanpsmt'),  # заголовок жирным
    ]))

    table_width, table_height = table.wrap(0, 0)
    if y - table_height < margin:
        c.showPage()
        y = height - margin
    table.drawOn(c, margin, y - table_height)
    y -= table_height + line_height

    # Итоговые строки
    c.setFont("timesnewromanpsmt", 10)
    c.drawString(margin, y, f"Итого материалов: {total_material:.2f} руб.")
    y -= line_height
    c.drawString(margin, y, f"Итого подрядчики: {total_contractor:.2f} руб.")
    y -= line_height
    c.drawString(margin, y, f"Себестоимость: {project.total_cost:.2f} руб.")
    y -= line_height

    company_markup = 0.2
    base_price = project.total_cost * (1 + company_markup)
    discount = base_price - project.final_client_price
    c.drawString(margin, y, f"Наценка компании (20%): {base_price - project.total_cost:.2f} руб.")
    y -= line_height
    c.drawString(margin, y, f"Скидка: {discount:.2f} руб.")
    y -= line_height
    c.setFont("timesnewromanpsmt", 12)
    c.drawString(margin, y, f"ИТОГО КЛИЕНТУ: {project.final_client_price:.2f} руб.")
    y -= line_height * 1.5
    c.setFont("timesnewromanpsmt", 10)
    c.drawString(margin, y, f"Прибыль: {project.final_client_price - project.total_cost:.2f} руб.")

    c.save()
    session.close()