from flask import Flask, request, jsonify, render_template, redirect
from flask_cors import CORS
import uuid, json, time, os, csv
from urllib.request import urlopen
from urllib.parse import quote

app = Flask(__name__)
CORS(app)

sessions = {}

BOXES = {
    "郵局小箱": {"w": 23, "h": 18, "d": 19},
    "郵局中箱": {"w": 39, "h": 27, "d": 23},
    "好市多牛奶箱": {"w": 40, "h": 30, "d": 30},
}

COLORS = [
    "#378ADD", "#1D9E75", "#D85A30", "#7F77DD",
    "#BA7517", "#993556", "#0F6E56", "#A32D2D",
    "#534AB7", "#3B6D11", "#993C1D", "#185FA5",
]

PRODUCTS_SHEET_ID = "1tyJYRWVPl7F5kprBylR_WbbIVayIWQEUxdQ-2sCL-cM"
ORDERS_SHEET_ID = "13HB7e9mzL0H6Nhfyl-AKhjO8M_GElnqPldTk-u-0ni8"
ORDERS_SHEET = "訂單明細"
PRODUCTS_SHEET = "產品清單"
product_cache = {}
cache_time = 0

def load_products():
    global product_cache, cache_time
    if time.time() - cache_time < 3600 and product_cache:
        return product_cache
    try:
        url = f"https://docs.google.com/spreadsheets/d/{PRODUCTS_SHEET_ID}/gviz/tq?tqx=out:csv&sheet={quote(PRODUCTS_SHEET)}"
        response = urlopen(url)
        lines = response.read().decode("utf-8").splitlines()
        reader = csv.reader(lines)
        next(reader)
        products = {}
        for row in reader:
            if len(row) < 15:
                continue
            pid = row[0].strip()
            name = row[10].strip() if len(row) > 10 else pid
            try:
                w = float(row[12]) if row[12].strip() else 10
                h = float(row[14]) if row[14].strip() else 10
                d = float(row[13]) if row[13].strip() else 10
            except:
                w, h, d = 10, 10, 10
            products[pid] = {"name": name, "w": w, "h": h, "d": d}
        product_cache = products
        cache_time = time.time()
        return products
    except Exception as e:
        print(f"載入產品清單失敗: {e}")
        return {}

def load_order_items(order_id):
    try:
        url = f"https://docs.google.com/spreadsheets/d/{ORDERS_SHEET_ID}/gviz/tq?tqx=out:csv&sheet={quote(ORDERS_SHEET)}"
        response = urlopen(url)
        lines = response.read().decode("utf-8").splitlines()
        reader = csv.reader(lines)
        next(reader)
        items = []
        for row in reader:
            if len(row) < 6:
                continue
            if str(row[1]).strip() == str(order_id).strip():
                pid = row[4].strip()
                try:
                    qty = int(float(row[5]))
                except:
                    qty = 1
                items.append({"product_id": pid, "qty": qty})
        return items
    except Exception as e:
        print(f"載入訂單明細失敗: {e}")
        return []

def try_pack(items, box):
    bw, bh, bd = box["w"], box["h"], box["d"]
    packed = []
    current_y = 0
    layer_num = 0
    all_items = []
    for item in items:
        for _ in range(item["qty"]):
            all_items.append(dict(item))
    remaining = list(all_items)
    while remaining:
        layer_items = []
        layer_h = 0
        x_cursor = 0
        z_cursor = 0
        row_d = 0
        still_remaining = []
        for item in remaining:
            placed = False
            for orientation in ["直立", "橫放"]:
                if orientation == "直立":
                    iw, ih, id_ = item["w"], item["h"], item["d"]
                else:
                    iw, ih, id_ = item["w"], item["d"], item["h"]
                if iw > bw or id_ > bd or ih > bh:
                    continue
                if x_cursor + iw <= bw:
                    if id_ > row_d:
                        row_d = id_
                    layer_items.append({
                        "name": item["name"], "color": item["color"],
                        "x": x_cursor, "y": current_y, "z": z_cursor,
                        "w": iw, "h": ih, "d": id_,
                        "orientation": orientation, "layer": layer_num + 1,
                    })
                    if ih > layer_h:
                        layer_h = ih
                    x_cursor += iw
                    placed = True
                    break
                elif z_cursor + row_d + id_ <= bd:
                    z_cursor += row_d
                    row_d = id_
                    x_cursor = 0
                    if x_cursor + iw <= bw:
                        layer_items.append({
                            "name": item["name"], "color": item["color"],
                            "x": x_cursor, "y": current_y, "z": z_cursor,
                            "w": iw, "h": ih, "d": id_,
                            "orientation": orientation, "layer": layer_num + 1,
                        })
                        if ih > layer_h:
                            layer_h = ih
                        x_cursor += iw
                        placed = True
                        break
            if not placed:
                still_remaining.append(item)
        if not layer_items:
            break
        packed.extend(layer_items)
        current_y += layer_h
        layer_num += 1
        remaining = still_remaining
        if current_y > bh:
            return {"success": False, "packed": packed, "layers": layer_num,
                    "utilization": 0, "remaining": len(remaining)}
    success = len(remaining) == 0
    total_vol = bw * bh * bd
    used_vol = sum(p["w"] * p["h"] * p["d"] for p in packed)
    utilization = round(used_vol / total_vol * 100)
    return {"success": success, "packed": packed, "layers": layer_num,
            "utilization": utilization, "remaining": len(remaining)}

def do_pack(order_id, raw_items):
    products = load_products()
    items = []
    for i, item in enumerate(raw_items):
        pid = str(item.get("product_id", "")).strip()
        qty = int(item.get("qty", 1))
        if pid in products:
            p = products[pid]
            items.append({
                "name": p["name"], "w": p["w"], "h": p["h"], "d": p["d"],
                "qty": qty, "color": COLORS[i % len(COLORS)],
            })
        else:
            items.append({
                "name": item.get("name", pid),
                "w": float(item.get("w", 10)),
                "h": float(item.get("h", 10)),
                "d": float(item.get("d", 10)),
                "qty": qty, "color": COLORS[i % len(COLORS)],
            })
    result = None
    chosen_box = None
    for box_name, box_dims in BOXES.items():
        r = try_pack(items, box_dims)
        if r["success"]:
            result = r
            chosen_box = box_name
            break
    if result is None:
        box_name = "好市多牛奶箱"
        result = try_pack(items, BOXES[box_name])
        chosen_box = box_name + "（仍有部分放不下）"
    session_id = str(uuid.uuid4())[:8]
    sessions[session_id] = {
    "order_id": order_id,
    "box": chosen_box,
    "box_dims": BOXES.get(chosen_box.replace("（仍有部分放不下）", ""), BOXES["好市多牛奶箱"]),
    "products": items,
    "result": result,
    "ts": time.time(),
}
    now = time.time()
    expired = [k for k, v in sessions.items() if now - v["ts"] > 86400]
    for k in expired:
        del sessions[k]
    return session_id

@app.route("/pack-redirect")
def pack_redirect():
    order_id = request.args.get("order_id", "")
    if not order_id:
        return "缺少 order_id", 400
    raw_items = load_order_items(order_id)
    if not raw_items:
        return f"找不到訂單 {order_id} 的明細", 404
    session_id = do_pack(order_id, raw_items)
    base_url = os.environ.get("BASE_URL", request.host_url.rstrip("/"))
    return redirect(f"{base_url}/view/{session_id}")

@app.route("/pack", methods=["POST"])
def pack():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400
    raw_items = data.get("items", [])
    order_id = data.get("order_id", "")
    session_id = do_pack(order_id, raw_items)
    base_url = os.environ.get("BASE_URL", request.host_url.rstrip("/"))
    session = sessions[session_id]
    return jsonify({
        "session_id": session_id,
        "box": session["box"],
        "layers": session["result"]["layers"],
        "utilization": session["result"].get("utilization", 0),
        "success": session["result"]["success"],
        "view_url": f"{base_url}/view/{session_id}",
    })

@app.route("/view/<session_id>")
def view(session_id):
    session = sessions.get(session_id)
    if not session:
        return "<h2 style='font-family:sans-serif;padding:2rem'>找不到此裝箱結果，可能已過期（24小時）</h2>", 404
    return render_template("result.html", session=session, session_id=session_id)

@app.route("/")
def index():
    return jsonify({"status": "ok", "message": "裝箱 API 運行中"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
