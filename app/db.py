"""SQLite 持久层：所有录入数据真实落库，跨重启/刷新持久存在。"""
import os
import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
# 生产环境请把持久卷挂载到 /app/data 并设置环境变量 DATA_DIR=/app/data，
# 这样 SQLite 数据库与抓取图片在容器重启后依然存在。
DATA_DIR = os.environ.get("DATA_DIR", BASE)
DB = os.path.join(DATA_DIR, "app.db")
UPLOAD = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD, exist_ok=True)


def conn():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    # WAL 支持多用户并发：读写可并行，配合 busy_timeout 避免写冲突锁死
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=30000")
    c.execute("PRAGMA synchronous=NORMAL")
    return c


def init():
    c = conn()
    cur = c.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS shops(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, owner TEXT, email TEXT, url TEXT, grp TEXT,
            role TEXT DEFAULT 'agent',
            price REAL, image TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS sku(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            official_sku TEXT, official_url TEXT,
            agent_shop TEXT, agent_sku TEXT, agent_url TEXT,
            official_price REAL, agent_price REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS standards(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, page_type TEXT, hex_color TEXT,
            logo_x REAL, logo_y REAL, logo_w REAL, logo_h REAL,
            forbidden_fonts TEXT, image TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            finished_at TEXT);
        CREATE TABLE IF NOT EXISTS issues(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER, shop_id INTEGER,
            type TEXT, severity TEXT,
            similarity REAL, price_official REAL, price_agent REAL, diff REAL,
            official_img TEXT, agent_img TEXT, annotation TEXT,
            status TEXT DEFAULT 'pending', note TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
        CREATE TABLE IF NOT EXISTS email_template(
            id INTEGER PRIMARY KEY CHECK(id=1), subject TEXT, body TEXT);
        CREATE TABLE IF NOT EXISTS targets(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT, official_url TEXT, agent_url TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS members(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, department TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS activity_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER,
            member_name TEXT,
            action TEXT,
            resource TEXT,
            detail TEXT,
            ref_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_log(id DESC);
        CREATE TABLE IF NOT EXISTS inspections(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            shop_host TEXT,
            agent_url TEXT NOT NULL,
            official_url TEXT NOT NULL,
            image_type TEXT,
            state TEXT DEFAULT 'queued',
            status TEXT DEFAULT 'pending',
            off_main TEXT, off_sku TEXT, off_detail TEXT,
            ag_main TEXT, ag_sku TEXT, ag_detail TEXT,
            cmp_main TEXT, cmp_sku TEXT, cmp_detail TEXT,
            price_official REAL, price_agent REAL,
            note TEXT, annotation TEXT, error TEXT,
            cookies TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            by_member INTEGER);
        """
    )
    cur.execute("INSERT OR IGNORE INTO settings(k,v) VALUES('visual_threshold','90')")
    cur.execute("INSERT OR IGNORE INTO settings(k,v) VALUES('price_tolerance','5')")
    # AI 视觉大模型比对（OpenAI 兼容接口；API Key 走环境变量，绝不入库）
    cur.execute("INSERT OR IGNORE INTO settings(k,v) VALUES('vision_enabled','0')")
    cur.execute("INSERT OR IGNORE INTO settings(k,v) VALUES('vision_base_url','https://api.openai.com/v1')")
    cur.execute("INSERT OR IGNORE INTO settings(k,v) VALUES('vision_model','gpt-4o')")
    cur.execute(
        "INSERT OR IGNORE INTO email_template(id,subject,body) VALUES(1,?,?)",
        (
            "【巡检违规整改通知】{shop}",
            "尊敬的 {shop} 负责人：\n经 AI 视觉合规巡检，贵店「{sku}」存在{type}违规：{detail}。\n请于 3 个工作日内完成整改并重新提交核验。\n\n—— 项目中心 · AI电商视觉合规巡检系统",
        ),
    )
    # 增量迁移：为 issues / tasks 增加真实抓取所需的字段（已存在则忽略）
    for col in ("official_url TEXT", "agent_url TEXT", "sku TEXT"):
        try:
            cur.execute(f"ALTER TABLE issues ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass
    try:
        cur.execute("ALTER TABLE tasks ADD COLUMN note TEXT")
    except sqlite3.OperationalError:
        pass
    # 增量迁移：inspections 增加 cookies 列（淘宝/天猫登录态）
    try:
        cur.execute("ALTER TABLE inspections ADD COLUMN cookies TEXT")
    except sqlite3.OperationalError:
        pass
    # 状态精简：取消「已核销」，统一用「已修改」作为闭环终态
    cur.execute("UPDATE issues SET status='modified' WHERE status='verified'")
    # 增量迁移：inspections 增加「独立核销态 + 凭证留痕」所需字段
    for col, typ in (
        ("verified_at TEXT", "TEXT"),
        ("verified_by INTEGER", "INTEGER"),
        ("verified_by_name TEXT", "TEXT"),
        ("evidence_path TEXT", "TEXT"),
    ):
        try:
            cur.execute(f"ALTER TABLE inspections ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass
    c.commit()
    c.close()


def get_setting(k, default=None):
    c = conn()
    row = c.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
    c.close()
    return row["v"] if row else default


def list_members():
    c = conn()
    rows = c.execute("SELECT * FROM members ORDER BY id ASC").fetchall()
    c.close()
    return [dict(r) for r in rows]


def add_member(name, department):
    c = conn()
    cur = c.execute(
        "INSERT INTO members(name, department) VALUES(?, ?)", (name, department)
    )
    c.commit()
    rid = cur.lastrowid
    row = c.execute("SELECT * FROM members WHERE id=?", (rid,)).fetchone()
    c.close()
    return dict(row)


def delete_member(mid):
    c = conn()
    c.execute("DELETE FROM members WHERE id=?", (mid,))
    c.commit()
    c.close()
    return {"ok": True}


def get_member(mid):
    c = conn()
    row = c.execute("SELECT * FROM members WHERE id=?", (mid,)).fetchone()
    c.close()
    return dict(row) if row else None


def log_activity(member_id, member_name, action, resource, detail, ref_id=None):
    """记录一次协作操作，供「团队协作动态」展示与审计。失败静默不影响主流程。"""
    try:
        c = conn()
        c.execute(
            "INSERT INTO activity_log(member_id,member_name,action,resource,detail,ref_id) "
            "VALUES(?,?,?,?,?,?)",
            (member_id, member_name, action, resource, detail, ref_id),
        )
        c.commit()
        c.close()
    except Exception:
        pass


def recent_activity(limit=60):
    """返回最近的操作记录（最新在前），用于协作动态流。"""
    c = conn()
    rows = c.execute(
        "SELECT * FROM activity_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


# ---------------- 精准对照表巡检 ----------------
def create_inspection(agent_url, official_url, image_type=None, title=None,
                       by_member=None, cookies=None):
    """新建一条精准对照表巡检（只比对用户给定的 代理商链接 / 官旗标准链接 这一对）。

    cookies：可选，淘宝/天猫登录态 Cookie（未登录会被登录墙拦截，需填此项才能抓到商品图）。
    """
    c = conn()
    cur = c.execute(
        "INSERT INTO inspections(agent_url, official_url, image_type, title, by_member, cookies) "
        "VALUES(?,?,?,?,?,?)",
        (agent_url, official_url, image_type, title, by_member, cookies))
    c.commit()
    rid = cur.lastrowid
    row = c.execute("SELECT * FROM inspections WHERE id=?", (rid,)).fetchone()
    c.close()
    return dict(row)


def list_inspections(status=None, state=None):
    c = conn()
    q = "SELECT * FROM inspections WHERE 1=1"
    args = []
    if status:
        q += " AND status=?"
        args.append(status)
    if state:
        q += " AND state=?"
        args.append(state)
    q += " ORDER BY id DESC"
    rows = c.execute(q, args).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_inspection(iid):
    c = conn()
    row = c.execute("SELECT * FROM inspections WHERE id=?", (iid,)).fetchone()
    c.close()
    return dict(row) if row else None


def update_inspection(iid, **fields):
    fields = {k: v for k, v in fields.items() if v is not None}
    if not fields:
        return get_inspection(iid)
    sets = ", ".join(f"{k}=?" for k in fields) + ", updated_at=CURRENT_TIMESTAMP"
    c = conn()
    c.execute(f"UPDATE inspections SET {sets} WHERE id=?", list(fields.values()) + [iid])
    c.commit()
    row = c.execute("SELECT * FROM inspections WHERE id=?", (iid,)).fetchone()
    c.close()
    return dict(row) if row else None


def delete_inspection(iid):
    c = conn()
    c.execute("DELETE FROM inspections WHERE id=?", (iid,))
    c.commit()
    c.close()
    return {"ok": True}
