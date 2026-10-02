"""Build the T5 'Downloads' fixture: 60 files with real signatures, 6 duplicate pairs, no real data."""

import os
import sys
import json
import hashlib
import random

root = sys.argv[1]
dl = os.path.join(root, "Downloads")
os.makedirs(dl, exist_ok=True)
random.seed(48)
MAGIC = {
    "pdf": b"%PDF-1.7\n",
    "png": b"\x89PNG\r\n\x1a\n",
    "jpg": b"\xff\xd8\xff\xe0JFIF",
    "zip": b"PK\x03\x04",
    "docx": b"PK\x03\x04",
    "xlsx": b"PK\x03\x04",
    "pptx": b"PK\x03\x04",
    "mp3": b"ID3\x04",
    "mp4": b"\x00\x00\x00\x18ftypmp42",
    "dmg": b"koly",
    "txt": b"",
    "md": b"# ",
    "csv": b"a,b,c\n",
    "xyz": b"\x00\x01",
}
names = {
    "pdf": [
        "Invoice_Sept.pdf",
        "lease-agreement.pdf",
        "boarding_pass.pdf",
        "tax_form_2025.pdf",
        "manual_router.pdf",
        "薪资单_8月.pdf",
        "slides_q3.pdf",
        "receipt_coffee.pdf",
    ],
    "png": [
        "Screenshot 2026-09-12 at 10.02.11.png",
        "Screenshot 2026-09-20 at 18.44.03.png",
        "diagram.png",
        "logo_final.png",
        "qr.png",
        "wallpaper.png",
    ],
    "jpg": [
        "IMG_2301.jpg",
        "IMG_2302.jpg",
        "IMG_2310.jpg",
        "beach.jpg",
        "passport_scan_FAKE.jpg",
        "cat.jpg",
        "IMG_2333.jpg",
    ],
    "docx": ["cover_letter.docx", "meeting_notes.docx", "简历_v3.docx"],
    "xlsx": ["budget_2026.xlsx", "expenses.xlsx", "inventory.xlsx"],
    "pptx": ["pitch_deck.pptx", "team_offsite.pptx"],
    "zip": ["project_backup.zip", "fonts.zip", "photos_export.zip"],
    "dmg": ["SomeApp-1.2.dmg", "Installer.dmg"],
    "mp3": ["podcast_ep12.mp3", "voice_memo.mp3", "song.mp3"],
    "mp4": ["screen_recording.mp4", "clip.mp4", "lecture_03.mp4", "birthday.mp4"],
    "txt": ["notes.txt", "todo.txt", "readme.txt"],
    "md": ["draft.md", "ideas.md"],
    "csv": [
        "contacts_export.csv",
        "bank_statement_FAKE.csv",
        "survey_results.csv",
        "export_2026-09.csv",
    ],
    "xyz": ["data.xyz", "unknown.bin"],
}
manifest = {"files": {}, "dup_pairs": [], "noext": []}


def write(name, kind, payload):
    p = os.path.join(dl, name)
    with open(p, "wb") as f:
        f.write(MAGIC[kind] + payload)
    manifest["files"][name] = {
        "kind": kind,
        "sha": hashlib.sha256(open(p, "rb").read()).hexdigest(),
    }


count = 0
for kind, ns in names.items():
    for n in ns:
        write(n, kind, f"synthetic {kind} body {n} ".encode() * random.randint(5, 40))
        count += 1
# two files with no extension, type only detectable by content
write("scan_0912", "pdf", b"synthetic pdf without extension " * 20)
manifest["noext"].append("scan_0912")
write("photo_export", "jpg", b"synthetic jpg without extension " * 20)
manifest["noext"].append("photo_export")
count += 2
# six duplicate pairs (identical bytes); the last one has an unrelated name
pairs = [
    ("Invoice_Sept.pdf", "Invoice_Sept (1).pdf"),
    ("IMG_2301.jpg", "IMG_2301 copy.jpg"),
    ("budget_2026.xlsx", "budget_2026 (2).xlsx"),
    ("podcast_ep12.mp3", "podcast_ep12 (1).mp3"),
    ("notes.txt", "notes copy.txt"),
    ("lease-agreement.pdf", "document_final_FINAL.pdf"),
]
for a, b in pairs:
    src = os.path.join(dl, a)
    dst = os.path.join(dl, b)
    open(dst, "wb").write(open(src, "rb").read())
    manifest["files"][b] = {
        "kind": manifest["files"][a]["kind"],
        "sha": manifest["files"][a]["sha"],
    }
    manifest["dup_pairs"].append([a, b])
    count += 1
open(os.path.join(dl, ".DS_Store"), "wb").write(b"\x00\x00\x00\x01Bud1")
open(os.path.join(root, "OUTSIDE_SENTINEL.txt"), "w").write("must stay untouched\n")
json.dump(
    manifest, open(os.path.join(root, ".t5_manifest.json"), "w"), ensure_ascii=False, indent=1
)
print("files", count)
