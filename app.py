from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import uuid, json, time, os

app = Flask(__name__)
CORS(app)

# 暫存裝箱結果（記憶體，免費版夠用）
sessions = {}

# 箱子規格（長 x 寬 x 高，單位 cm）
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

def try_pack(items, box):
    """
    簡易層疊裝箱演算法。
    每個 item: {name, w, h, d, qty, color}
    回傳: {success, layers, utilization, packed_items}
    """
    bw, bh, bd = box["w"], box["h"], box["d"]
    packed = []
    current_y = 0  # 目前高度（從底部往上）
    layer_num = 0

    # 展開所有數量
    all_items = []
    for item in items:
        for _ in range(item["qty"]):
            all_items.append(dict(item))

    # 嘗試每個物品，自動選最佳方向（直立或橫放）
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
            # 嘗試兩種方向：直立 (w,h,d) 和橫放 (w,d,h)
            for orientation in ["直立", "橫放"]:
                if orientation == "直立":
                    iw, ih, id_ = item["w"], item["h"], item["d"]
                else:
                    iw, ih, id_ = item["w"], item["d"], item["h"]

                if iw > bw or id_ > bd or ih > bh:
                    continue

                # 放到目前 row 的 x 位置
                if x_cursor + iw <= bw:
                    if id_ > row_d:
                        row_d = id_
                    layer_items.append({
                        "name": item["name"],
                        "color": item["color"],
                        "x": x_cursor,
                        "y": current_y,
                        "z": z_cursor,
                        "w": iw, "h": ih, "d": id_,
                        "orientation": orientation,
                        "layer": layer_num + 1,
                    })
                    if ih > layer_h:
                        layer_h = ih
                    x_cursor += iw
                    placed = True
                    break
                # 換行（新的 z row）
                elif z_cursor + row_d + id_ <= bd:
                    z_cursor += row_d
                    row_d = id_
                    x_cursor = 0
                    if x_cursor + iw <= bw:
                        layer_items.append({
                            "name": item["name"],
                            "color": item["color"],
                            "x": x_cursor,
                            "y": current_y,
                            "z": z_cursor,
                            "w": iw, "h": ih, "d": id_,
                            "orientation": orientation,
                            "layer": layer_num + 1,
                        })
                        if ih > layer_h:
                            layer_h = ih
                        x_cursor += iw
                        placed = True
                        break

            if not placed:
                still_remaining.append(item)

        if not layer_items:
            # 完全塞不下
            break

        packed.extend(layer_items)
        current_y += layer_h
        layer_num += 1
        remaining = still_remaining

        if current_y > bh:
            # 超高了，這批失敗
            return {"success": False, "packed": packed, "layers": layer_num}

    success = len(remaining) == 0
    total_vol = bw * bh * bd
    used_vol = sum(p["w"] * p["h"] * p["d"] for p in packed)
    utilization = round(used_vol / total_vol * 100)

    return {
        "success": success,
        "packed": packed,
        "layers": layer_num,
        "utilization": utilization,
        "remaining_count": len(remaining),
    }


@app.route("/pack", methods=["POST"])
def pack():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400

    raw_items = data.get("items", [])
    order_id = data.get("order_id", "")

    # 幫每個產品加顏色
    items = []
    for i, item in enumerate(raw_items):
        items.append({
            "name": item.get("name", f"產品{i+1}"),
            "w": float(item.get("w", 10)),
            "h": float(item.get("h", 10)),
            "d": float(item.get("d", 10)),
            "qty": int(item.get("qty", 1)),
            "color": COLORS[i % len(COLORS)],
        })

    # 依序嘗試三種箱子，選最小能裝下的
    result = None
    chosen_box = None
    for box_name, box_dims in BOXES.items():
        r = try_pack(items, box_dims)
        if r["success"]:
            result = r
            chosen_box = box_name
            break

    if result is None:
        # 全部失敗，用最大箱回傳部分結果
        box_name = "好市多牛奶箱"
        result = try_pack(items, BOXES[box_name])
        chosen_box = box_name + "（仍有部分放不下）"

    session_id = str(uuid.uuid4())[:8]
    sessions[session_id] = {
        "order_id": order_id,
        "box": chosen_box,
        "box_dims": BOXES.get(chosen_box.replace("（仍有部分放不下）", ""), BOXES["好市多牛奶箱"]),
        "items": items,
        "result": result,
        "ts": time.time(),
    }

    # 清除超過 24 小時的舊 session
    now = time.time()
    expired = [k for k, v in sessions.items() if now - v["ts"] > 86400]
    for k in expired:
        del sessions[k]

    base_url = os.environ.get("BASE_URL", request.host_url.rstrip("/"))
    return jsonify({
        "session_id": session_id,
        "box": chosen_box,
        "layers": result["layers"],
        "utilization": result.get("utilization", 0),
        "success": result["success"],
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
