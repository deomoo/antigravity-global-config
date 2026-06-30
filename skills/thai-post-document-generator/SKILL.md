---
name: thai-post-document-generator
description: Official Thailand Post document layout structure and Gemini draft automation templates.
---

# Thailand Post Document Generator Skill

This skill provides python-docx templates and prompt guidelines for drafting official documents and memos (หนังสือราชการ ปณท.) aligned with Thai government style and formatting rules.

## 1. Document Format & Typography (TH Sarabun PSK)

Standard configuration parameters for generating official Thai Post documents:
- **Font Family**: "TH Sarabun PSK" (or "TH Sarabun New")
- **Line Spacing**: 1.15
- **Margins**: Top/Bottom 2.5 cm, Left 3.0 cm, Right 2.0 cm
- **Garuda/Logo Alignment**: Top Center (หนังสือภายนอก) or Top Left (หนังสือภายใน/บันทึกข้อความ)

```python
from docx import Document
from docx.shared import Inches, Pt, Cm
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

def init_thai_document():
    doc = Document()
    
    # Configure page margins
    sections = doc.sections
    for section in sections:
        section.top_margin = Cm(2.5)
        section.bottom_margin = Cm(2.5)
        section.left_margin = Cm(3.0)
        section.right_margin = Cm(2.0)
        
    # Configure default paragraph font
    style = doc.styles['Normal']
    font = style.font
    font.name = 'TH Sarabun PSK'
    font.size = Pt(16)
    
    return doc
```

## 2. Text Alignment & Government Terminology

- **ขึ้นต้นจดหมายภายนอก**: ใช้คำว่า "เรียน..."
- **ขึ้นต้นบันทึกข้อความภายใน**: ใช้คำว่า "เสนอ..."
- **การจัดย่อหน้า**: การจัดกึ่งแนวหลังใช้การกระจายแบบไทย (Thai Distributed / Justified) เพื่อความเป็นระเบียบและเรียบร้อยของตัวอักษรภาษาไทย
- **ลงท้ายจดหมาย**: ใช้ "ขอแสดงความนับถือ" สำหรับจดหมายส่งภายนอก

```python
from docx.enum.text import WD_ALIGN_PARAGRAPH

def add_thai_paragraph(doc, text, style_name='Normal', align=WD_ALIGN_PARAGRAPH.JUSTIFY):
    p = doc.add_paragraph(style_name=style_name)
    p.alignment = align
    run = p.add_run(text)
    # Force set font to TH Sarabun on run level
    run.font.name = 'TH Sarabun PSK'
    run.font.size = Pt(16)
    return p
```

## 3. Document Numbering Format

Official Thailand Post document numbers follow the structure:
`ที่ พณ. [รหัสสาขา] / [เลขรันจดหมาย] / [ปี พ.ศ.]`

Example for Na Haeo Post Office:
`ที่ พณ. 42170 / 128 / 2569`
- `พณ.`: ย่อมาจาก ไปรษณีย์ไทย
- `42170`: รหัสไปรษณีย์/สาขา ณ อ.นาแห้ว
- `128`: ลำดับเอกสารส่งออกประจำปี
- `2569`: ปี พ.ศ. ปัจจุบัน (ปีพุทธศักราช)
