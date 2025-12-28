import streamlit as st
from pydantic import BaseModel
import graphviz
import datetime

# ==========================================
# 1. オントロジー定義
# ==========================================

class Supplier(BaseModel):
    id: str
    name: str
    country: str
    status: str = "Normal"

class Material(BaseModel):
    id: str
    name: str
    supplier_id: str

class Factory(BaseModel):
    id: str
    name: str
    status: str = "Normal"

class Product(BaseModel):
    id: str
    name: str
    stock: int
    factory_id: str
    material_required_id: str

class Order(BaseModel):
    id: str
    customer_name: str
    product_id: str
    quantity: int
    priority: str

# ==========================================
# 2. データ初期化 & 状態管理
# ==========================================

def init_data():
    if 'db' not in st.session_state:
        st.session_state.db = {
            "suppliers": {
                "S01": Supplier(id="S01", name="株式会社グローバル・チップ", country="Taiwan", status="Normal"),
                "S02": Supplier(id="S02", name="株式会社日本鋼材", country="Japan", status="Normal"),
            },
            "materials": {
                "M01": Material(id="M01", name="高性能ロジック半導体", supplier_id="S01"),
                "M02": Material(id="M02", name="高耐久ステンレス筐体", supplier_id="S02"),
            },
            "factories": {
                "F01": Factory(id="F01", name="京都マザー工場 (精密組立)", status="Normal"),
                "F02": Factory(id="F02", name="深セン組立センター", status="Normal"),
            },
            "products": {
                "P01": Product(id="P01", name="自律走行ロボ『運び屋くん』", stock=50, factory_id="F01", material_required_id="M01"),
                "P02": Product(id="P02", name="農業用ドローン『緑風』", stock=120, factory_id="F02", material_required_id="M01"),
                "P03": Product(id="P03", name="産業用アーム『剛腕』", stock=10, factory_id="F02", material_required_id="M02"),
            },
            "orders": {
                "O101": Order(id="O101", customer_name="帝国重工 (VIP)", product_id="P01", quantity=80, priority="High"),
                "O102": Order(id="O102", customer_name="スタートアップA社", product_id="P01", quantity=10, priority="Normal"),
                "O103": Order(id="O103", customer_name="物流サービスB社", product_id="P03", quantity=5, priority="Normal"),
            }
        }
    
    if 'last_report' not in st.session_state:
        st.session_state.last_report = None
    
    if 'supplier_candidates' not in st.session_state:
        st.session_state.supplier_candidates = None

init_data()

# ==========================================
# 3. ロジック: Graph Context & Actions
# ==========================================

def get_full_context(product_id: str):
    db = st.session_state.db
    product = db["products"][product_id]
    factory = db["factories"][product.factory_id]
    material = db["materials"][product.material_required_id]
    supplier = db["suppliers"][material.supplier_id]
    
    related_orders = [o for o in db["orders"].values() if o.product_id == product.id]
    total_demand = sum(o.quantity for o in related_orders)
    vip_orders = [o for o in related_orders if o.priority == "High"]
    
    return {
        "product": product,
        "factory": factory,
        "material": material,
        "supplier": supplier,
        "orders": related_orders,
        "metrics": {
            "demand": total_demand,
            "shortage": total_demand - product.stock,
            "has_vip": len(vip_orders) > 0
        }
    }

def render_network_graph(ctx):
    g = graphviz.Digraph()
    g.attr(rankdir='LR', bgcolor='transparent')
    
    # ノード色のロジック（赤色をはっきりさせる修正済み）
    s_color = "red" if ctx['supplier'].status != "Normal" else "lightblue"
    g.node("Sup", f"Supplier\n{ctx['supplier'].name}\n({ctx['supplier'].status})", shape="box", style="filled", fillcolor=s_color)
    
    g.node("Mat", f"Material\n{ctx['material'].name}", shape="ellipse", style="filled", fillcolor="white")
    
    f_color = "red" if ctx['factory'].status != "Normal" else "lightblue"
    g.node("Fac", f"Factory\n{ctx['factory'].name}\n({ctx['factory'].status})", shape="box", style="filled", fillcolor=f_color)
    
    p_color = "orange" if ctx['metrics']['shortage'] > 0 else "lightgreen"
    g.node("Prod", f"Product\n{ctx['product'].name}\nStock: {ctx['product'].stock}", shape="doubleoctagon", style="filled", fillcolor=p_color)
    
    for order in ctx['orders']:
        o_color = "gold" if order.priority == "High" else "white"
        g.node(f"Ord_{order.id}", f"Order\n{order.customer_name}\nQty: {order.quantity}", shape="note", style="filled", fillcolor=o_color)
        g.edge("Prod", f"Ord_{order.id}")

    g.edge("Sup", "Mat")
    g.edge("Mat", "Fac")
    g.edge("Fac", "Prod")
    return g

def simulate_ai_analysis(ctx):
    issues = []
    actions = []
    
    if ctx['supplier'].status != "Normal":
        issues.append(f"🚨 **サプライヤートラブル**: {ctx['supplier'].name} ({ctx['supplier'].status}) の影響で部品供給が停止しています。")
        if st.session_state.supplier_candidates is None:
            actions.append({"label": "🔍 代替サプライヤーを検索", "key": "search_sup", "type": "primary"})
        else:
            issues.append("ℹ️ **アクション待機中**: 以下のリストから発注先を選択してください。")
        
    if ctx['factory'].status != "Normal":
        issues.append(f"⚠️ **工場稼働停止**: {ctx['factory'].name} が稼働していません。")
        
    if ctx['metrics']['shortage'] > 0:
        issues.append(f"📉 **在庫不足**: 現在庫 {ctx['product'].stock} に対し、需要が {ctx['metrics']['demand']} あります。")
        if ctx['metrics']['has_vip']:
             issues.append("👑 **VIP顧客リスク**: 重要顧客の注文が含まれています。")
             actions.append({"label": "📦 在庫のVIP優先割り当て", "key": "alloc_vip", "type": "secondary"})
        if ctx['supplier'].status == "Normal" and ctx['factory'].status == "Normal":
             actions.append({"label": "🏭 緊急増産 (+50)", "key": "production_boost", "type": "secondary"})

    if not issues:
        return "✅ **状況正常**: 現在、対処すべきリスクはありません。", []
    
    return "\n\n".join(issues), actions

# ==========================================
# 4. アクション実行ロジック
# ==========================================

def execute_search_supplier():
    candidates = [
        {"id": "EXT_A", "name": "テック・マテリアルズ (国内)", "price": "高 (1.2倍)", "eta": "明日", "rating": "A"},
        {"id": "EXT_B", "name": "アジアパーツ・エクスプレス", "price": "安 (0.8倍)", "eta": "1週間", "rating": "B"},
        {"id": "EXT_C", "name": "大阪精密部品", "price": "並 (1.0倍)", "eta": "3日", "rating": "A"}
    ]
    st.session_state.supplier_candidates = candidates
    st.toast("検索完了: 3社の候補が見つかりました")

def execute_procurement(candidate):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    report = {
        "title": "代替調達 発注完了",
        "time": timestamp,
        "message": f"選定された **{candidate['name']}** へ緊急発注を行いました。",
        "changes": [
            {"item": "発注先", "before": "グローバル・チップ (停止中)", "after": f"**{candidate['name']}**"},
            {"item": "納期予定", "before": "未定", "after": candidate['eta']},
            {"item": "調達コスト", "before": "標準", "after": candidate['price']}
        ]
    }
    st.session_state.last_report = report
    st.session_state.supplier_candidates = None
    st.toast(f"発注完了: {candidate['name']}")

def execute_other_action(action_key, ctx):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    db = st.session_state.db
    report = {"time": timestamp, "action": action_key, "details": []}

    if action_key == "alloc_vip":
        vip_orders = [o for o in ctx['orders'] if o.priority == "High"]
        target = vip_orders[0].customer_name if vip_orders else "VIP"
        report["title"] = "VIP優先割り当て完了"
        report["message"] = f"在庫を {target} 様向けに確保しました。"
        report["changes"] = [{"item": "ステータス", "before": "未引当", "after": "引当済"}]

    elif action_key == "production_boost":
        old = db["products"][ctx['product'].id].stock
        db["products"][ctx['product'].id].stock += 50
        report["title"] = "増産指示 送信完了"
        report["message"] = "工場へ緊急製造ラインの稼働を指示しました。"
        report["changes"] = [{"item": "在庫数", "before": str(old), "after": f"**{old+50}**"}]
    
    st.session_state.last_report = report

# ==========================================
# 5. UI構築 (Streamlit)
# ==========================================

st.set_page_config(layout="wide", page_title="Ontology Procurement Demo")

st.title("🌐 Supply Chain Control Tower")
st.caption("Human-in-the-loop: Search -> Select -> Execute")

# --- Sidebar: Ontology Explorer ---
with st.sidebar:
    st.header("📂 Ontology Explorer")
    st.caption("オブジェクトを選択して詳細を確認・操作できます")

    # 1. Product Object (Main View Focus)
    st.subheader("📦 Product Object")
    selected_p_id = st.selectbox(
        "分析対象を選択", 
        list(st.session_state.db["products"].keys()), 
        format_func=lambda x: st.session_state.db["products"][x].name
    )
    
    st.markdown("---")
    st.subheader("🏭 Supply Chain Objects")
    
    # 2. Supplier Object
    st.markdown("**Supplier Object**")
    target_s = st.selectbox(
        "サプライヤー選択", 
        list(st.session_state.db["suppliers"].keys()), 
        format_func=lambda x: st.session_state.db["suppliers"][x].name
    )
    # Simulator Controls for Supplier
    s_status_map = {"🟢 正常": "Normal", "🔴 停止 (Disrupted)": "Disrupted"}
    current_s_status = st.session_state.db["suppliers"][target_s].status
    # ラジオボタンのデフォルト値を現在のステータスに合わせる工夫
    default_index = 0 if current_s_status == "Normal" else 1
    new_s_status = s_status_map[st.radio(
        "Status Change", 
        list(s_status_map.keys()), 
        index=default_index,
        key="s_radio",
        label_visibility="collapsed"
    )]
    st.session_state.db["suppliers"][target_s].status = new_s_status

    # 3. Material Object (New! 閲覧のみ)
    st.markdown("**Material Object**")
    target_m = st.selectbox(
        "素材・部品選択", 
        list(st.session_state.db["materials"].keys()), 
        format_func=lambda x: st.session_state.db["materials"][x].name
    )
    # Materialに関連するSupplierを表示してあげる（リンクの可視化）
    linked_supplier_id = st.session_state.db["materials"][target_m].supplier_id
    linked_supplier_name = st.session_state.db["suppliers"][linked_supplier_id].name
    st.info(f"🔗 Link: {linked_supplier_name}")

    # 4. Factory Object
    st.markdown("**Factory Object**")
    target_f = st.selectbox(
        "工場選択", 
        list(st.session_state.db["factories"].keys()), 
        format_func=lambda x: st.session_state.db["factories"][x].name
    )
    # Simulator Controls for Factory
    f_status_map = {"🟢 正常": "Normal", "🔧 メンテ": "Maintenance", "🔥 停止": "Critical"}
    current_f_status = st.session_state.db["factories"][target_f].status
    
    # index検索
    f_keys = list(f_status_map.values())
    try:
        f_idx = f_keys.index(current_f_status)
    except ValueError:
        f_idx = 0
        
    new_f_status = f_status_map[st.radio(
        "Factory Status", 
        list(f_status_map.keys()), 
        index=f_idx,
        key="f_radio",
        label_visibility="collapsed"
    )]
    st.session_state.db["factories"][target_f].status = new_f_status


# --- Main ---
ctx = get_full_context(selected_p_id)
col_viz, col_ai = st.columns([1.6, 1])

with col_viz:
    st.subheader("🔗 Semantic Graph")
    # 赤色が見えやすいように修正されたグラフ関数を使用
    graph = render_network_graph(ctx)
    st.graphviz_chart(graph, use_container_width=True)
    with st.expander("📊 詳細データ"):
        st.json({"Product": ctx['product'].dict(), "Metrics": ctx['metrics']})

with col_ai:
    st.subheader("🤖 AI Assistant")

    # 1. レポート表示
    if st.session_state.last_report:
        rep = st.session_state.last_report
        with st.container():
            st.success(f"✅ **{rep['title']}**")
            st.write(rep['message'])
            if "changes" in rep:
                for c in rep["changes"]:
                    c1, c2, c3 = st.columns([2, 2, 2])
                    c1.caption(c["item"])
                    c2.text(c["before"] + " →")
                    c3.markdown(c["after"])
            if st.button("閉じる", key="close_rep"):
                st.session_state.last_report = None
                st.rerun()
        st.divider()

    # 2. AI分析
    analysis_text, recommended_actions = simulate_ai_analysis(ctx)
    with st.chat_message("assistant"):
        st.markdown(analysis_text)
    
    # 3. アクションボタン
    if recommended_actions:
        st.markdown("##### 🚀 Actions")
        for action in recommended_actions:
            safe_type = action.get("type", "secondary")
            if st.button(action["label"], key=action["key"], type=safe_type, use_container_width=True):
                if action["key"] == "search_sup":
                    execute_search_supplier()
                else:
                    execute_other_action(action["key"], ctx)
                st.rerun()

    # 4. 候補リスト表示
    if st.session_state.supplier_candidates:
        st.info("💡 以下の候補が見つかりました。発注先を選択してください。")
        candidates = st.session_state.supplier_candidates
        for cand in candidates:
            with st.container(border=True):
                c1, c2 = st.columns([3, 1])
                with c1:
                    st.markdown(f"**{cand['name']}**")
                    st.caption(f"納期: {cand['eta']} | コスト: {cand['price']} | 評価: {cand['rating']}")
                with c2:
                    if st.button("発注", key=f"btn_{cand['id']}", type="primary"):
                        execute_procurement(cand)
                        st.rerun()
        
        if st.button("キャンセル (検索結果を破棄)"):
            st.session_state.supplier_candidates = None
            st.rerun()