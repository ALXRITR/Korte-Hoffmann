# pip install pikepdf
import os, re, sys, traceback
import pikepdf as pp
from pikepdf import Pdf

# ====== Paths ======
try:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    BASE_DIR = os.getcwd()

INPUT_DIR  = os.path.join(BASE_DIR, ".sort")
OUTPUT_DIR = os.path.join(BASE_DIR, ".export")
ICC_PROFILE_PATH = r"C:\Windows\System32\spool\drivers\color\ISOcoated_v2_300_eci.icc"

print(f"[INFO] BASE_DIR:   {BASE_DIR}")
print(f"[INFO] INPUT_DIR:  {INPUT_DIR}")
print(f"[INFO] OUTPUT_DIR: {OUTPUT_DIR}")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ====== Color maps (0..1) ======
RICH_BLACK = (0.60, 0.50, 0.40, 1.00)
PAPER_WHITE= (0.00, 0.00, 0.00, 0.00)
AI_GREY    = (0.46, 0.43, 0.40, 0.35)  # #736A6A
BUILD_GRN  = (0.52, 0.22, 0.63, 0.29)  # #6C845C
REAL_ESTATE= (0.70, 0.45, 0.16, 0.20)  # #4D6D94

def hex2rgb01(h):
    h = h.lstrip('#'); r=int(h[0:2],16); g=int(h[2:4],16); b=int(h[4:6],16)
    return (r/255.0, g/255.0, b/255.0)

MAP = [
    (hex2rgb01("#000000"), RICH_BLACK),
    (hex2rgb01("#FFFFFF"), PAPER_WHITE),
    (hex2rgb01("#736A6A"), AI_GREY),
    (hex2rgb01("#6C845C"), BUILD_GRN),
    (hex2rgb01("#4D6D94"), REAL_ESTATE),
]

EPS = 0.002
def close3(a,b,eps=EPS): return all(abs(a[i]-b[i])<=eps for i in (0,1,2))
def fmt4(c): return f"{c[0]:.6g} {c[1]:.6g} {c[2]:.6g} {c[3]:.6g}"

# RGB or ICC-RGB (fill/stroke) and Gray
RE_RGB  = re.compile(rb'([-+]?\d*\.?\d+)\s+([-+]?\d*\.?\d+)\s+([-+]?\d*\.?\d+)\s+(rg|RG|scn|SCN)')
RE_GRAY = re.compile(rb'([-+]?\d*\.?\d+)\s+(g|G)')

def replace_stream_bytes(b: bytes) -> tuple[bytes, int]:
    reps = 0

    def repl_rgb(m):
        nonlocal reps
        r = float(m.group(1)); g = float(m.group(2)); b = float(m.group(3))
        op = m.group(4).decode('latin1')
        for rgb, cmyk in MAP:
            if close3((r,g,b), rgb):
                reps += 1
                out = f"{fmt4(cmyk)} {'K' if op in ('RG','SCN') else 'k'}".encode('latin1')
                return out
        return m.group(0)

    def repl_gray(m):
        nonlocal reps
        val = float(m.group(1)); op = m.group(2).decode('latin1')
        if abs(val-0.0) <= EPS:
            reps += 1
            return f"{fmt4(RICH_BLACK)} {'K' if op=='G' else 'k'}".encode('latin1')
        if abs(val-1.0) <= EPS:
            reps += 1
            return f"{fmt4(PAPER_WHITE)} {'K' if op=='G' else 'k'}".encode('latin1')
        return m.group(0)

    b2 = RE_RGB.sub(repl_rgb, b)
    b3 = RE_GRAY.sub(repl_gray, b2)
    return b3, reps

def read_contents_as_list(page) -> list[pp.Stream]:
    cont = page.obj.get('/Contents', None)
    if cont is None:
        return []
    if isinstance(cont, pp.Stream):
        return [cont]
    if isinstance(cont, pp.Array):
        return [s for s in cont if isinstance(s, pp.Stream)]
    return []

def write_contents_from_list(pdf, page, streams: list[pp.Stream]):
    if not streams:
        return
    if len(streams) == 1:
        page.obj['/Contents'] = streams[0]
    else:
        page.obj['/Contents'] = pp.Array(streams)

def embed_output_intent(pdf: Pdf, icc_path: str):
    if not os.path.isfile(icc_path):
        print("[WARN] ICC profile not found. Skipping OutputIntent.")
        return
    with open(icc_path, 'rb') as f:
        icc_bytes = f.read()
    icc_stream = pdf.make_stream(icc_bytes)  # indirect stream
    oi_dict = pp.Dictionary({
        '/Type': pp.Name('/OutputIntent'),
        '/S': pp.Name('/GTS_PDFX'),
        '/OutputConditionIdentifier': pp.String("ISO Coated v2 300% (ECI)"),
        '/OutputCondition': pp.String("ISO Coated v2 300% (ECI)"),
        '/DestOutputProfile': icc_stream
    })
    oi = pdf.make_indirect(oi_dict)
    root = pdf.root
    if '/OutputIntents' in root and isinstance(root['/OutputIntents'], pp.Array):
        root['/OutputIntents'].append(oi)
    else:
        root['/OutputIntents'] = pp.Array([oi])
    print("[INFO] OutputIntent embedded: ISO Coated v2 300% (ECI)")

# ====== Start ======
if not os.path.isdir(INPUT_DIR):
    print("[ERROR] INPUT_DIR does not exist.")
    sys.exit(1)

files = [f for f in os.listdir(INPUT_DIR) if f.lower().endswith(".pdf")]
print(f"[INFO] PDFs found: {len(files)}")
if not files:
    print("[HINT] Put PDFs into .sort and rerun.")
    sys.exit(0)

total_files = 0
total_pages = 0
total_reps  = 0

for fname in files:
    try:
        in_path = os.path.join(INPUT_DIR, fname)
        base = fname[:-4]
        out_base = base[:-4] + "_cmyk" if base.endswith("_rgb") else base + "_cmyk"
        out_path = os.path.join(OUTPUT_DIR, out_base + ".pdf")

        print(f"\n[FILE] {fname} → {out_base}.pdf")
        pdf = Pdf.open(in_path)

        file_reps = 0
        page_count = len(pdf.pages)
        for i, page in enumerate(pdf.pages, start=1):
            streams = read_contents_as_list(page)
            if not streams:
                print(f"  [PAGE {i}/{page_count}] no /Contents")
                continue

            new_streams = []
            page_reps = 0
            for idx, s in enumerate(streams):
                data = s.read_bytes()
                new_data, reps = replace_stream_bytes(data)
                page_reps += reps
                new_streams.append(pdf.make_stream(new_data))

            write_contents_from_list(pdf, page, new_streams)
            if page_reps:
                print(f"  [PAGE {i}/{page_count}] replacements: {page_reps}")
            total_reps += page_reps
            file_reps  += page_reps
        total_pages += page_count

        try:
            embed_output_intent(pdf, ICC_PROFILE_PATH)
        except Exception as e:
            print(f"[WARN] OutputIntent failed: {e}. Continuing without it.")

        pdf.save(out_path)
        pdf.close()
        total_files += 1
        print(f"[OK]  saved: {out_path}")
        if file_reps == 0:
            print("      note: 0 replacements in this file")

    except Exception as e:
        print(f"[FAIL] {fname}: {e}")
        traceback.print_exc()

print("\n===== SUMMARY =====")
print(f"Processed files : {total_files}")
print(f"Total pages     : {total_pages}")
print(f"Total replaces  : {total_reps}")
print(f"Output folder   : {OUTPUT_DIR}")
