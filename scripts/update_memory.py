import os
import sys
import re
import subprocess
from datetime import datetime
from pathlib import Path

# Fix encoding issues on Windows
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='ignore')
        sys.stderr.reconfigure(encoding='utf-8', errors='ignore')
    except AttributeError:
        pass

# Config
GLOBAL_CONFIG_DIR = r"C:\Users\deomo\.gemini\config"
SYNC_SCRIPT = os.path.join(GLOBAL_CONFIG_DIR, "scripts", "sync_memory.py")

def find_project_memory():
    """ค้นหาไฟล์ .agents/AGENTS.md ที่อยู่ใกล้ที่สุดกับโฟลเดอร์รันงานปัจจุบัน"""
    curr = Path(os.getcwd()).resolve()
    # ตรวจหาในโฟลเดอร์แม่ขึ้นไปเรื่อยๆ
    for parent in [curr] + list(curr.parents):
        local_agent_md = parent / ".agents" / "AGENTS.md"
        if local_agent_md.exists():
            return local_agent_md
    return None

def append_to_learning_log(filepath, date_str, title, content=""):
    """เพิ่มข้อมูลในหัวข้อ Continuous Learning Log & Active Retention"""
    content_str = filepath.read_text(encoding="utf-8")
    
    # สร้างข้อความที่จะแทรก
    new_entry = f"- **[{date_str}] {title}**: {content}\n"
    
    # มองหาหัวข้อ Continuous Learning Log แบบยืดหยุ่น (รองรับทั้ง ## 🔄 1. และ ## 🔄 3.)
    pattern = r"(## 🔄 \d+\. Continuous Learning Log[^\n]*)"
    match = re.search(pattern, content_str)
    
    if match:
        header_pos = match.end()
        # แทรกหลังหัวข้อ
        updated_content = content_str[:header_pos] + "\n\n" + new_entry + content_str[header_pos:].lstrip("\n")
        
        # ทำการบีบอัดข้อมูล (Compaction) หากแถวการบันทึกยาวเกิน 8 แถว
        lines = updated_content.splitlines()
        learning_section_idx = -1
        for idx, line in enumerate(lines):
            if "## 🔄" in line and "Continuous Learning Log" in line:
                learning_section_idx = idx
                break
                
        if learning_section_idx != -1:
            # นับจำนวนบันทึกภายใต้หัวข้อนี้ (นับเครื่องหมายขีดกลาง "-")
            log_entries = []
            scan_idx = learning_section_idx + 1
            while scan_idx < len(lines):
                if lines[scan_idx].startswith("##") and not lines[scan_idx].startswith("###"):
                    break
                if lines[scan_idx].strip().startswith("-"):
                    log_entries.append(scan_idx)
                scan_idx += 1
                
            # หากยาวเกิน 8 รายการ ให้เก็บ 4 รายการล่าสุดไว้ และรวบรวมตัวที่เหลือ
            if len(log_entries) > 8:
                print("⚠️ Memory count exceeds 8. Running auto-compaction...")
                to_compact_indices = log_entries[4:]  # รายการเก่าๆ (รายการหลังตัวที่ 4 เป็นต้นไป)
                compacted_summary = []
                for idx_to_comp in to_compact_indices:
                    compacted_summary.append(lines[idx_to_comp].replace("- ", "").strip())
                
                # ลบแถวเก่าๆ ออก
                for idx_to_del in sorted(to_compact_indices, reverse=True):
                    lines.pop(idx_to_del)
                
                # เพิ่มแถวสรุปรวบยอดตัวเก่า
                summary_line = f"- *[Compacted Past Memory Summary]:* {', '.join(compacted_summary[:3])}..."
                lines.insert(log_entries[4], summary_line)
                updated_content = "\n".join(lines)
                
        filepath.write_text(updated_content, encoding="utf-8")
        print(f"Successfully updated memory in: {filepath}")
        return True
    else:
        print(f"Could not find Continuous Learning Log header in {filepath}")
        return False

def sync_to_github(msg):
    """เรียก sync_memory.py เพื่ออัปโหลดขึ้น GitHub"""
    if os.path.exists(SYNC_SCRIPT):
        print("Syncing memory to GitHub...")
        subprocess.Popen([sys.executable, SYNC_SCRIPT, msg], shell=True)
    else:
        print("sync_memory.py not found.")

def main():
    if len(sys.argv) < 3:
        print("Usage: python update_memory.py \"[Date] Title\" \"Content description\"")
        sys.exit(1)
        
    log_title = sys.argv[1]
    log_desc = sys.argv[2]
    
    # หาวันที่ปัจจุบัน
    date_match = re.search(r"\[(\d{4}-\d{2}-\d{2})\]", log_title)
    if date_match:
        date_str = date_match.group(1)
        clean_title = log_title.replace(f"[{date_str}]", "").strip()
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")
        clean_title = log_title.strip()

    # ตรวจสอบหาไฟล์
    target_memory = find_project_memory()
    if target_memory:
        project_name = target_memory.parent.parent.name
        commit_msg = f"Auto-update local memory for {project_name}: {clean_title}"
    else:
        target_memory = Path(GLOBAL_CONFIG_DIR) / "AGENTS.md"
        commit_msg = f"Auto-update global memory: {clean_title}"
        print("No project workspace memory found. Updating global AGENTS.md instead.")

    # อัปเดตข้อมูล
    success = append_to_learning_log(target_memory, date_str, clean_title, log_desc)
    
    # ซิงค์ Git
    if success:
        sync_to_github(commit_msg)

if __name__ == "__main__":
    main()
