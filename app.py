"""
Ontology Explorer — Supply Chain Control Tower

オントロジー(オブジェクト+リンクのグラフ)と、従来のデータ基盤(RDB+SQL)を
"同じ世界・同じ事故"で並べて触り、その設計思想の違いを体感するための学習用デモ。

3つのモード(タブ):
  🌐 Ontology Mode  : オブジェクトを辿って文脈を組み立て、AIが複合判断 → 人がWrite-back
  📊 Classic DB Mode: 同じデータをテーブルで持ち、関係はそのつどJOINで再構築
  ⚖️ Compare        : 同じ事故への対応を左右に並べ、手数・文脈・AI判断可否を比較

サイドバーの Chaos 注入(サプライヤー停止/工場停止)は両モードに同時反映される。
"""

import datetime
import sqlite3

import graphviz
import pandas as pd
import streamlit as st
from pydantic import BaseModel

# ==========================================================================
# 1. オントロジー定義 (Object Types) ─ 記事でいう "Schema is Semantic"
#    クラス定義そのものが「業務上の意味」。AIはこの構造から世界を読む。
# ==========================================================================


class Supplier(BaseModel):
    id: str
    name: str
    country: str
    status: str = "Normal"  # Normal | Disrupted


class Material(BaseModel):
    id: str
    name: str
    supplier_id: str  # ─── Link → Supplier


class Factory(BaseModel):
    id: str
    name: str
    status: str = "Normal"  # Normal | Maintenance | Critical


class Product(BaseModel):
    id: str
    name: str
    stock: int
    factory_id: str           # ─── Link → Factory
    material_required_id: str  # ─── Link → Material


class Order(BaseModel):
    id: str
    customer_name: str
    product_id: str  # ─── Link → Product
    quantity: int
    priority: str    # High | Normal


SUPPLIER_STATUS = {"🟢 正常": "Normal", "🔴 停止 (Disrupted)": "Disrupted"}
FACTORY_STATUS = {"🟢 正常": "Normal", "🔧 メンテ": "Maintenance", "🔥 停止": "Critical"}


# ==========================================================================
# 2. データ初期化 & 状態管理 (single source of truth)
# ==========================================================================


def seed_db():
    return {
        "suppliers": {
            "S01": Supplier(id="S01", name="株式会社グローバル・チップ", country="Taiwan"),
            "S02": Supplier(id="S02", name="株式会社日本鋼材", country="Japan"),
        },
        "materials": {
            "M01": Material(id="M01", name="高性能ロジック半導体", supplier_id="S01"),
            "M02": Material(id="M02", name="高耐久ステンレス筐体", supplier_id="S02"),
        },
        "factories": {
            "F01": Factory(id="F01", name="京都マザー工場 (精密組立)"),
            "F02": Factory(id="F02", name="深セン組立センター"),
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
        },
    }


def init_state():
    if "db" not in st.session_state:
        st.session_state.db = seed_db()
    st.session_state.setdefault("last_report", None)
    st.session_state.setdefault("supplier_candidates", None)


init_state()


# ==========================================================================
# 3. オントロジー側ロジック ─ "Graph is Context"
#    オブジェクトを起点にリンクを辿るだけで、AIに渡す文脈が組み上がる。
# ==========================================================================


def metrics_for(db, product_id):
    """製品1つ分の需要・在庫・不足・VIP有無。リンクを辿って注文を集計する。"""
    product = db["products"][product_id]
    related = [o for o in db["orders"].values() if o.product_id == product_id]
    demand = sum(o.quantity for o in related)
    return {
        "orders": related,
        "demand": demand,
        "shortage": demand - product.stock,
        "has_vip": any(o.priority == "High" for o in related),
    }


def get_full_context(db, product_id):
    """製品を起点に Factory → Material → Supplier → Orders まで一括収集。

    これがオントロジーの核心。"P01" と言うだけで、それを支える世界全体が
    リンク経由で芋づる式に集まる(=AIに渡す Context)。
    """
    product = db["products"][product_id]
    factory = db["factories"][product.factory_id]
    material = db["materials"][product.material_required_id]
    supplier = db["suppliers"][material.supplier_id]
    m = metrics_for(db, product_id)
    return {
        "product": product,
        "factory": factory,
        "material": material,
        "supplier": supplier,
        "orders": m["orders"],
        "metrics": {"demand": m["demand"], "shortage": m["shortage"], "has_vip": m["has_vip"]},
    }


def context_trace(ctx):
    """文脈をどのリンクを辿って組み立てたかを、人が読める手順にする。"""
    p, f, m, s = ctx["product"], ctx["factory"], ctx["material"], ctx["supplier"]
    return [
        f"起点  Product『{p.name}』(在庫 {p.stock})",
        f"  └─[.factory_id]→  Factory『{f.name}』({f.status})",
        f"  └─[.material_required_id]→  Material『{m.name}』",
        f"        └─[.supplier_id]→  Supplier『{s.name}』({s.status})",
        f"  ←[.product_id]──  Orders {len(ctx['orders'])}件 / 需要 {ctx['metrics']['demand']}",
    ]


def _status_color(node_status, focus, base):
    """ノード色。異常は常に強調、focus外は淡色。"""
    if node_status in ("Disrupted", "Critical"):
        return "#ff4d4d"
    if node_status == "Maintenance":
        return "#f0e68c"
    return base if focus else "#e8e8e8"


def build_overview_graph(db, focus_pid):
    """オントロジー"全体"を1枚に。選択製品のチェーンを濃く、他は淡く、異常は赤く。"""
    g = graphviz.Digraph()
    g.attr(rankdir="LR", bgcolor="transparent", fontname="Helvetica", nodesep="0.3", ranksep="0.8")
    g.attr("node", fontname="Helvetica", fontsize="10")
    g.attr("edge", color="#999999", arrowsize="0.7")

    # focus chain の id 集合
    chain = set()
    if focus_pid in db["products"]:
        p = db["products"][focus_pid]
        chain = {f"S:{db['materials'][p.material_required_id].supplier_id}",
                 f"M:{p.material_required_id}", f"F:{p.factory_id}", f"P:{p.id}"}
        chain |= {f"O:{o.id}" for o in db["orders"].values() if o.product_id == p.id}

    def foc(nid):
        return (not chain) or (nid in chain)

    for s in db["suppliers"].values():
        nid = f"S:{s.id}"
        g.node(nid, f"Supplier\n{s.name}\n({s.status})", shape="box", style="filled,rounded",
               fillcolor=_status_color(s.status, foc(nid), "#bcd9f0"),
               penwidth="2.5" if (chain and nid in chain) else "1")
    for m in db["materials"].values():
        nid = f"M:{m.id}"
        g.node(nid, f"Material\n{m.name}", shape="ellipse", style="filled",
               fillcolor="white" if foc(nid) else "#e8e8e8",
               penwidth="2.5" if (chain and nid in chain) else "1")
    for f in db["factories"].values():
        nid = f"F:{f.id}"
        g.node(nid, f"Factory\n{f.name}\n({f.status})", shape="box", style="filled,rounded",
               fillcolor=_status_color(f.status, foc(nid), "#bcd9f0"),
               penwidth="2.5" if (chain and nid in chain) else "1")
    for p in db["products"].values():
        nid = f"P:{p.id}"
        short = metrics_for(db, p.id)["shortage"]
        base = "#ffb877" if short > 0 else "#a8e6a3"
        g.node(nid, f"Product\n{p.name}\nStock {p.stock}", shape="doubleoctagon", style="filled",
               fillcolor=base if foc(nid) else "#e8e8e8",
               penwidth="2.5" if (chain and nid in chain) else "1")
    for o in db["orders"].values():
        nid = f"O:{o.id}"
        base = "#ffd700" if o.priority == "High" else "white"
        g.node(nid, f"Order\n{o.customer_name}\nQty {o.quantity}", shape="note", style="filled",
               fillcolor=base if foc(nid) else "#e8e8e8",
               penwidth="2.5" if (chain and nid in chain) else "1")

    # Links (= edges)。属性名がそのまま関係の意味。
    for m in db["materials"].values():
        g.edge(f"S:{m.supplier_id}", f"M:{m.id}", label="supplies")
    for p in db["products"].values():
        g.edge(f"M:{p.material_required_id}", f"F:{p.factory_id}", label="used in")
        g.edge(f"F:{p.factory_id}", f"P:{p.id}", label="builds")
    for o in db["orders"].values():
        g.edge(f"P:{o.product_id}", f"O:{o.id}", label="ordered")
    return g


def simulate_ai_analysis(ctx):
    """文脈(グラフ)を受け取って複合判断する。IDの羅列ではなく"意味"で考えている点が肝。"""
    issues, actions = [], []
    if ctx["supplier"].status != "Normal":
        issues.append(f"🚨 **サプライヤートラブル**: {ctx['supplier'].name} が停止。"
                      f" `Supplier→Material→Product` のリンクを辿ると本製品の部品供給が断たれます。")
        if st.session_state.supplier_candidates is None:
            actions.append({"label": "🔍 代替サプライヤーを検索", "key": "search_sup", "type": "primary"})
        else:
            issues.append("ℹ️ **アクション待機中**: 下のリストから発注先を選択してください。")
    if ctx["factory"].status != "Normal":
        issues.append(f"⚠️ **工場稼働停止**: {ctx['factory'].name} が稼働していません。")
    if ctx["metrics"]["shortage"] > 0:
        issues.append(f"📉 **在庫不足**: 在庫 {ctx['product'].stock} に対し需要 {ctx['metrics']['demand']}"
                      f"(不足 {ctx['metrics']['shortage']})。")
        if ctx["metrics"]["has_vip"]:
            issues.append("👑 **VIP顧客リスク**: High優先の注文が影響を受けます。")
            actions.append({"label": "📦 在庫のVIP優先割り当て", "key": "alloc_vip", "type": "secondary"})
        if ctx["supplier"].status == "Normal" and ctx["factory"].status == "Normal":
            actions.append({"label": "🏭 緊急増産 (+50)", "key": "production_boost", "type": "secondary"})
    if not issues:
        return "✅ **状況正常**: 現在、対処すべきリスクはありません。", []
    return "\n\n".join(issues), actions


# ----- Actions (Write-back) -----


def execute_search_supplier():
    st.session_state.supplier_candidates = [
        {"id": "EXT_A", "name": "テック・マテリアルズ (国内)", "price": "高 (1.2倍)", "eta": "明日", "rating": "A"},
        {"id": "EXT_B", "name": "アジアパーツ・エクスプレス", "price": "安 (0.8倍)", "eta": "1週間", "rating": "B"},
        {"id": "EXT_C", "name": "大阪精密部品", "price": "並 (1.0倍)", "eta": "3日", "rating": "A"},
    ]
    st.toast("検索完了: 3社の候補が見つかりました")


def execute_procurement(c):
    st.session_state.last_report = {
        "title": "代替調達 発注完了",
        "message": f"選定された **{c['name']}** へ緊急発注を行いました。",
        "changes": [
            {"item": "発注先", "before": "グローバル・チップ (停止中)", "after": f"**{c['name']}**"},
            {"item": "納期予定", "before": "未定", "after": c["eta"]},
            {"item": "調達コスト", "before": "標準", "after": c["price"]},
        ],
    }
    st.session_state.supplier_candidates = None
    st.toast(f"発注完了: {c['name']}")


def execute_other_action(key, ctx):
    db = st.session_state.db
    if key == "alloc_vip":
        vip = [o for o in ctx["orders"] if o.priority == "High"]
        target = vip[0].customer_name if vip else "VIP"
        st.session_state.last_report = {
            "title": "VIP優先割り当て完了",
            "message": f"在庫を {target} 様向けに確保しました。",
            "changes": [{"item": "ステータス", "before": "未引当", "after": "引当済"}],
        }
    elif key == "production_boost":
        old = db["products"][ctx["product"].id].stock
        db["products"][ctx["product"].id].stock += 50
        st.session_state.last_report = {
            "title": "増産指示 送信完了",
            "message": "工場へ緊急製造ラインの稼働を指示しました。",
            "changes": [{"item": "在庫数", "before": str(old), "after": f"**{old + 50}**"}],
        }


# ==========================================================================
# 4. 従来のデータ基盤(RDB) シミュレーション
#    同じ世界を "正規化されたテーブル" として持つ。関係は毎回JOINで再構築。
# ==========================================================================


def build_sqlite(db):
    """現在の(Chaos反映済み)状態から in-memory SQLite を毎回構築する。"""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE suppliers (id TEXT PRIMARY KEY, name TEXT, country TEXT, status TEXT);
        CREATE TABLE materials (id TEXT PRIMARY KEY, name TEXT, supplier_id TEXT);
        CREATE TABLE factories (id TEXT PRIMARY KEY, name TEXT, status TEXT);
        CREATE TABLE products  (id TEXT PRIMARY KEY, name TEXT, stock INT,
                                factory_id TEXT, material_required_id TEXT);
        CREATE TABLE orders    (id TEXT PRIMARY KEY, customer_name TEXT, product_id TEXT,
                                quantity INT, priority TEXT);
        """
    )
    cur.executemany("INSERT INTO suppliers VALUES (?,?,?,?)",
                    [(s.id, s.name, s.country, s.status) for s in db["suppliers"].values()])
    cur.executemany("INSERT INTO materials VALUES (?,?,?)",
                    [(m.id, m.name, m.supplier_id) for m in db["materials"].values()])
    cur.executemany("INSERT INTO factories VALUES (?,?,?)",
                    [(f.id, f.name, f.status) for f in db["factories"].values()])
    cur.executemany("INSERT INTO products VALUES (?,?,?,?,?)",
                    [(p.id, p.name, p.stock, p.factory_id, p.material_required_id)
                     for p in db["products"].values()])
    cur.executemany("INSERT INTO orders VALUES (?,?,?,?,?)",
                    [(o.id, o.customer_name, o.product_id, o.quantity, o.priority)
                     for o in db["orders"].values()])
    conn.commit()
    return conn


# 「停止中サプライヤーが脅かすVIP注文」を出すのに必要な4テーブルJOIN
IMPACT_SQL = """SELECT o.id          AS order_id,
       o.customer_name,
       o.priority,
       p.name        AS product,
       m.name        AS material,
       s.name        AS supplier,
       s.status      AS supplier_status
FROM orders o
JOIN products  p ON o.product_id           = p.id
JOIN materials m ON p.material_required_id  = m.id
JOIN suppliers s ON m.supplier_id          = s.id
WHERE s.status <> 'Normal'
  AND o.priority = 'High';"""


# ==========================================================================
# 5. UI
# ==========================================================================

st.set_page_config(layout="wide", page_title="Ontology vs DB — Control Tower", page_icon="🌐")

st.markdown(
    """
    <style>
      .legend span{display:inline-block;margin-right:14px;font-size:0.85rem;}
      .dot{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:4px;vertical-align:middle;}
      div[data-testid="stMetric"]{background:#f7f9fc;border:1px solid #e6e9ef;border-radius:10px;padding:8px 12px;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🌐 Supply Chain Control Tower")
st.caption("オントロジー vs 従来DB を、同じ世界・同じ事故で比べる学習デモ ｜ Human-in-the-loop: Search → Select → Execute")

# ----- Sidebar: 共有Chaos + 製品選択 -----
with st.sidebar:
    st.header("⚡ Chaos & Focus")
    st.caption("ここの操作は3タブすべてに同時反映されます")

    db = st.session_state.db

    selected_pid = st.selectbox(
        "🔎 分析対象 Product",
        list(db["products"].keys()),
        format_func=lambda x: db["products"][x].name,
    )

    st.markdown("---")
    st.subheader("🏭 状態を壊す (Chaos Engineering)")

    target_s = st.selectbox("Supplier", list(db["suppliers"].keys()),
                            format_func=lambda x: db["suppliers"][x].name)
    cur_s = db["suppliers"][target_s].status
    new_s = SUPPLIER_STATUS[st.radio(
        "Supplier status", list(SUPPLIER_STATUS.keys()),
        index=0 if cur_s == "Normal" else 1, key="s_radio", label_visibility="collapsed")]
    db["suppliers"][target_s].status = new_s

    target_f = st.selectbox("Factory", list(db["factories"].keys()),
                            format_func=lambda x: db["factories"][x].name)
    cur_f = db["factories"][target_f].status
    f_vals = list(FACTORY_STATUS.values())
    f_idx = f_vals.index(cur_f) if cur_f in f_vals else 0
    new_f = FACTORY_STATUS[st.radio(
        "Factory status", list(FACTORY_STATUS.keys()),
        index=f_idx, key="f_radio", label_visibility="collapsed")]
    db["factories"][target_f].status = new_f

    st.markdown("---")
    if st.button("♻️ 世界をリセット", width="stretch"):
        st.session_state.db = seed_db()
        st.session_state.last_report = None
        st.session_state.supplier_candidates = None
        st.rerun()

    st.info("💡 まず Supplier を 🔴停止 にして、各タブの反応の差を見比べてみてください。")

ctx = get_full_context(db, selected_pid)

tab_onto, tab_db, tab_cmp = st.tabs(["🌐 Ontology Mode", "📊 Classic DB Mode", "⚖️ Compare"])


# ======================== TAB 1: Ontology =================================
with tab_onto:
    st.markdown("#### データを **オブジェクトとリンクのグラフ** として扱う")
    col_viz, col_ai = st.columns([1.7, 1])

    with col_viz:
        st.markdown("##### 🔗 Semantic Graph (全体図 / 選択チェーンを強調)")
        st.graphviz_chart(build_overview_graph(db, selected_pid), width="stretch")
        st.markdown(
            """
            <div class="legend">
              <span><span class="dot" style="background:#bcd9f0"></span>正常</span>
              <span><span class="dot" style="background:#ff4d4d"></span>停止/異常</span>
              <span><span class="dot" style="background:#f0e68c"></span>メンテ</span>
              <span><span class="dot" style="background:#ffb877"></span>在庫不足</span>
              <span><span class="dot" style="background:#a8e6a3"></span>在庫OK</span>
              <span><span class="dot" style="background:#ffd700"></span>VIP注文</span>
              <span><span class="dot" style="background:#e8e8e8"></span>非選択(淡色)</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        m = ctx["metrics"]
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("在庫", ctx["product"].stock)
        k2.metric("需要", m["demand"])
        k3.metric("過不足", -m["shortage"], delta=None)
        k4.metric("VIP", "あり" if m["has_vip"] else "なし")

        st.markdown("##### 🧭 Context Trace — リンクを辿って文脈を組み立てた経路")
        st.code("\n".join(context_trace(ctx)), language="text")
        st.caption("↑ AIにはこの『文脈のかたまり』が渡る。IDだけ渡すのとは情報量が違う。")

    with col_ai:
        st.markdown("##### 🤖 AI Assistant")
        if st.session_state.last_report:
            rep = st.session_state.last_report
            st.success(f"✅ **{rep['title']}**")
            st.write(rep["message"])
            for c in rep.get("changes", []):
                c1, c2, c3 = st.columns([2, 2, 2])
                c1.caption(c["item"])
                c2.text(c["before"] + " →")
                c3.markdown(c["after"])
            if st.button("閉じる", key="close_rep"):
                st.session_state.last_report = None
                st.rerun()
            st.divider()

        analysis, recs = simulate_ai_analysis(ctx)
        with st.chat_message("assistant"):
            st.markdown(analysis)

        if recs:
            st.markdown("###### 🚀 Actions (Write-back)")
            for a in recs:
                if st.button(a["label"], key=a["key"], type=a.get("type", "secondary"), width="stretch"):
                    if a["key"] == "search_sup":
                        execute_search_supplier()
                    else:
                        execute_other_action(a["key"], ctx)
                    st.rerun()

        if st.session_state.supplier_candidates:
            st.info("💡 候補が見つかりました。発注先を選択してください。")
            for cand in st.session_state.supplier_candidates:
                with st.container(border=True):
                    cc1, cc2 = st.columns([3, 1])
                    cc1.markdown(f"**{cand['name']}**")
                    cc1.caption(f"納期: {cand['eta']} | コスト: {cand['price']} | 評価: {cand['rating']}")
                    if cc2.button("発注", key=f"buy_{cand['id']}", type="primary"):
                        execute_procurement(cand)
                        st.rerun()
            if st.button("キャンセル", key="cancel_cand"):
                st.session_state.supplier_candidates = None
                st.rerun()


# ======================== TAB 2: Classic DB ===============================
with tab_db:
    st.markdown("#### 同じデータを **正規化テーブル** で扱う（従来のデータ基盤）")
    st.caption("関係は明示的に保持されず、必要になるたび JOIN で再構築する。")

    conn = build_sqlite(db)

    st.markdown("##### 🗄️ Tables")
    t1, t2, t3 = st.columns(3)
    with t1:
        st.caption("suppliers")
        st.dataframe(pd.read_sql_query("SELECT * FROM suppliers", conn), hide_index=True, width="stretch")
        st.caption("materials")
        st.dataframe(pd.read_sql_query("SELECT * FROM materials", conn), hide_index=True, width="stretch")
    with t2:
        st.caption("factories")
        st.dataframe(pd.read_sql_query("SELECT * FROM factories", conn), hide_index=True, width="stretch")
        st.caption("orders")
        st.dataframe(pd.read_sql_query("SELECT * FROM orders", conn), hide_index=True, width="stretch")
    with t3:
        st.caption("products")
        st.dataframe(pd.read_sql_query("SELECT * FROM products", conn), hide_index=True, width="stretch")

    st.markdown("---")
    st.markdown("##### ❓ 問い: 「いま停止中のサプライヤーが脅かす **VIP注文** は？」")
    st.caption("オントロジーなら状態を1つ変えるだけでAIが即答した問い。RDBでは…")

    st.markdown("これに答えるには **4テーブルを JOIN** する必要がある:")
    sql = st.text_area("SQL (編集可)", value=IMPACT_SQL, height=240, key="impact_sql")

    if st.button("▶️ クエリ実行", type="primary", key="run_sql"):
        try:
            res = pd.read_sql_query(sql, conn)
            st.session_state["sql_result"] = res
        except Exception as e:  # noqa: BLE001
            st.session_state["sql_result"] = None
            st.error(f"SQLエラー: {e}")

    res = st.session_state.get("sql_result")
    if res is not None:
        if len(res):
            st.dataframe(res, hide_index=True, width="stretch")
            st.warning(
                "⚠️ 得られたのは **平たい結果表**。"
                "『次にどのサプライヤーへ切り替えるか』『増産すべきか』はここには無い。"
                "判断はすべて人間の頭の中、もしくは別途また別のクエリが要る。"
            )
        else:
            st.success("該当なし(=いま停止中サプライヤーに紐づくVIP注文は無い)。Supplierを🔴にして再実行してみて。")

    st.markdown("---")
    st.markdown("##### 🤖 「AIに渡す」とどうなるか")
    cda, cdb = st.columns(2)
    with cda:
        st.markdown("**RDB: フラットな行(ID中心)**")
        st.code(
            "order_id | product_id | material_required_id | supplier_id\n"
            "O101     | P01        | M01                  | S01\n"
            "（…関係は外部キーIDのまま。意味はスキーマ外の暗黙知）",
            language="text",
        )
        st.caption("AIは ID の対応表を別途与えられないと『何が起きているか』を組み立てられない。")
    with cdb:
        st.markdown("**Ontology: 文脈のかたまり**")
        st.code("\n".join(context_trace(ctx)), language="text")
        st.caption("リンクを辿った文脈ごと渡るので、AIは複合状況をそのまま判断できる。")


# ======================== TAB 3: Compare ==================================
with tab_cmp:
    st.markdown("#### ⚖️ 同じ事故 → 同じゴール、対応を並べて比べる")
    disrupted = [s.name for s in db["suppliers"].values() if s.status != "Normal"]
    if disrupted:
        st.error(f"🚨 現在の事故: サプライヤー **{', '.join(disrupted)}** が停止中")
    else:
        st.info("💡 サイドバーで Supplier を 🔴停止 にすると、両者の差がはっきり出ます。")

    st.caption("ゴール: 「この事故で危ないVIP注文を特定し、代替調達まで実行する」")

    left, right = st.columns(2)
    with left:
        st.markdown("### 📊 従来DB (RDB)")
        st.markdown(
            "1. どのテーブルに関係があるか**人が把握**\n"
            "2. orders⋈products⋈materials⋈suppliers の **4 JOIN を記述**\n"
            "3. 結果は**平たい表**。意味づけは人の頭の中\n"
            "4. 『代替先は?』は別クエリ / 別システム\n"
            "5. 発注は**また別の画面(基幹システム)**で手作業\n"
        )
        st.metric("必要クエリ数(概算)", "3〜4本")
        st.error("見る画面 と やる画面 が分断。AIに渡せるのは ID中心の断片。")

    with right:
        st.markdown("### 🌐 オントロジー")
        st.markdown(
            "1. 製品を1つ指定 → **リンクが文脈を自動収集**\n"
            "2. status を1つ変えるだけで **AIが複合判断**\n"
            "3. リスク(供給断+VIP+不足)を**まとめて提示**\n"
            "4. 代替候補も**同じ画面**に提案\n"
            "5. ボタンで **Write-back**(発注/増産)を即実行\n"
        )
        st.metric("必要クエリ数(概算)", "0本(辿るだけ)")
        st.success("見る と やる が統合。AIに渡るのは 文脈グラフ そのもの。")

    st.markdown("---")
    st.markdown("##### まとめ: 何が本質的に違うのか")
    st.dataframe(
        pd.DataFrame(
            {
                "観点": ["関係の保持", "文脈の取得", "AIに渡る情報", "分析→実行", "スキーマの役割"],
                "従来DB (RDB)": ["外部キー(暗黙)", "都度JOIN", "ID中心の平たい行", "別システムに分断",
                                "データの“持ち方”を定義"],
                "オントロジー": ["リンク(明示・一級)", "辿るだけ(自動)", "意味づき文脈グラフ", "同一画面でWrite-back",
                               "ビジネスの“意味”を定義"],
            }
        ),
        hide_index=True,
        width="stretch",
    )
    st.caption("※ RDBが劣るという話ではなく、"
               "『AIに意思決定させる』目的では“意味と関係を一級市民にする”オントロジー設計が効く、という対比。")
