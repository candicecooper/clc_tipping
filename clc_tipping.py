import streamlit as st
from supabase import create_client, Client
from datetime import date
import pandas as pd

st.set_page_config(
    page_title="CLC Footy Tipping",
    page_icon="🏉",
    layout="wide",
    initial_sidebar_state="collapsed"
)

@st.cache_resource
def init_supabase() -> Client:
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
supabase = init_supabase()

try:
    ADMIN_PW = st.secrets["TIPPING_ADMIN_PASSWORD"]
except Exception:
    ADMIN_PW = "tipping2026"

AFL_TEAMS = [
    "Adelaide","Brisbane Lions","Carlton","Collingwood","Essendon",
    "Fremantle","Geelong","Gold Coast","GWS Giants","Hawthorn",
    "Melbourne","North Melbourne","Port Adelaide","Richmond",
    "St Kilda","Sydney","West Coast","Western Bulldogs"
]

# ─── STYLES ──────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
html,body,[class*="css"]{font-family:'Inter',sans-serif;}
.block-container{padding-top:1.2rem;max-width:960px;}
.hero{background:linear-gradient(135deg,#002B5C,#005EB8);color:white;
      border-radius:14px;padding:1.5rem 2rem;margin-bottom:1.5rem;
      box-shadow:0 4px 20px rgba(0,43,92,0.3);}
.hero h1{margin:0;font-size:1.8rem;font-weight:800;}
.hero p{margin:0.3rem 0 0;opacity:0.8;font-size:0.92rem;}
.ladder-row{background:white;border-radius:10px;padding:0.7rem 1rem;
            margin-bottom:0.4rem;display:flex;align-items:center;
            box-shadow:0 1px 6px rgba(0,0,0,0.07);border-left:4px solid #005EB8;}
.ladder-row.top1{border-left-color:#FFD700;}
.ladder-row.top2{border-left-color:#C0C0C0;}
.ladder-row.top3{border-left-color:#CD7F32;}
.pos-badge{font-weight:800;font-size:1.1rem;color:#002B5C;width:28px;text-align:center;}
.staff-name{font-weight:600;font-size:0.95rem;color:#1a2e44;flex:1;margin:0 1rem;}
.afl-nick{font-size:0.75rem;color:#888;margin-left:0.3rem;}
.pts-total{font-weight:800;font-size:1.1rem;color:#005EB8;min-width:60px;text-align:right;}
.pts-label{font-size:0.65rem;color:#aaa;text-align:right;}
.round-score{font-size:0.78rem;color:#555;min-width:40px;text-align:center;
             background:#f0f4f8;border-radius:6px;padding:0.15rem 0.4rem;margin:0 0.15rem;}
.section-title{font-weight:700;font-size:0.75rem;text-transform:uppercase;
               letter-spacing:0.1em;color:#888;margin:1.5rem 0 0.6rem;}
.winner-crown{font-size:1.4rem;margin-right:0.4rem;}
</style>
""", unsafe_allow_html=True)

# ─── DB HELPERS ──────────────────────────────────────────────────────────────
def db_participants():
    return supabase.table("tipping_participants")\
        .select("*").order("name").execute().data or []

def db_rounds():
    return supabase.table("tipping_rounds")\
        .select("*").order("round_number").execute().data or []

def db_scores():
    return supabase.table("tipping_scores")\
        .select("*").execute().data or []

def db_add_participant(name, afl_nick):
    supabase.table("tipping_participants").insert(
        {"name": name, "afl_nickname": afl_nick}
    ).execute()

def db_get_staff_list():
    try:
        return supabase.table("staff_list")             .select("id,name,email").eq("active", True).order("name").execute().data or []
    except Exception as e:
        st.error(f"Could not load staff list: {e}")
        return []

def db_add_all_staff(staff_list, existing_names):
    """Add all active staff not already in tipping_participants, one at a time to avoid bulk insert errors."""
    to_add = [s for s in staff_list if s["name"] not in existing_names]
    added = 0
    errors = []
    for s in to_add:
        try:
            supabase.table("tipping_participants").insert(
                {"name": s["name"], "afl_nickname": ""}
            ).execute()
            added += 1
        except Exception as e:
            errors.append(f"{s['name']}: {e}")
    if errors:
        st.warning(f"Some staff could not be added: {'; '.join(errors[:3])}")
    return added

def db_del_participant(pid):
    supabase.table("tipping_scores").delete().eq("participant_id", pid).execute()
    supabase.table("tipping_participants").delete().eq("id", pid).execute()

def db_add_round(num, label):
    supabase.table("tipping_rounds").insert(
        {"round_number": num, "round_label": label, "round_date": str(date.today())}
    ).execute()

def db_save_score(participant_id, round_id, score):
    # upsert
    supabase.table("tipping_scores").upsert(
        {"participant_id": participant_id, "round_id": round_id, "score": score},
        on_conflict="participant_id,round_id"
    ).execute()

def db_del_round(rid):
    supabase.table("tipping_scores").delete().eq("round_id", rid).execute()
    supabase.table("tipping_rounds").delete().eq("id", rid).execute()

# ─── BUILD LADDER ─────────────────────────────────────────────────────────────
def build_ladder(participants, rounds, scores):
    """Returns list of dicts sorted by total desc."""
    # index scores
    score_idx = {}
    for s in scores:
        score_idx[(s["participant_id"], s["round_id"])] = s["score"]

    rows = []
    for p in participants:
        total = 0
        round_scores = []
        for r in rounds:
            sc = score_idx.get((p["id"], r["id"]), None)
            total += sc if sc is not None else 0
            round_scores.append(sc)
        rows.append({
            "id":          p["id"],
            "name":        p["name"],
            "afl_nickname":p.get("afl_nickname",""),
            "total":       total,
            "round_scores":round_scores,
        })
    rows.sort(key=lambda x: (-x["total"], x["name"]))
    return rows

# ─── AUTH ─────────────────────────────────────────────────────────────────────
if "tipping_admin" not in st.session_state:
    st.session_state.tipping_admin = False

# ─── HEADER ──────────────────────────────────────────────────────────────────
st.markdown("""
<div class="hero">
  <div style="display:flex;align-items:center;gap:1rem;">
    <span style="font-size:3rem;">🏉</span>
    <div>
      <h1>CLC Footy Tipping 2026</h1>
      <p>Cowandilla Learning Centre — Season Ladder</p>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# Admin toggle — shown inline at top right
hcol1, hcol2 = st.columns([5, 2])
with hcol2:
    if not st.session_state.tipping_admin:
        with st.expander("🔐 Admin login"):
            pw = st.text_input("Password", type="password", key="admin_pw")
            if st.button("Sign In", type="primary", use_container_width=True):
                if pw == ADMIN_PW:
                    st.session_state.tipping_admin = True
                    st.rerun()
                else:
                    st.error("Incorrect password")
    else:
        st.success("✅ Admin mode")
        if st.button("🔓 Sign Out", use_container_width=True):
            st.session_state.tipping_admin = False
            st.rerun()

# ─── LOAD DATA ────────────────────────────────────────────────────────────────
participants = db_participants()
rounds       = db_rounds()
scores       = db_scores()
ladder       = build_ladder(participants, rounds, scores)

# ─── LADDER ──────────────────────────────────────────────────────────────────
if not participants:
    st.info("No participants yet — an admin needs to add staff members first.")
else:
    # Show last N rounds in the ladder (up to 5 most recent)
    recent_rounds = rounds[-5:] if len(rounds) > 5 else rounds

    # Round headers
    if recent_rounds:
        cols_hdr = st.columns([0.5, 4.5] + [1]*len(recent_rounds) + [1.5])
        with cols_hdr[0]: st.markdown("<div style='font-size:0.7rem;color:#aaa;text-align:center;'>#</div>", unsafe_allow_html=True)
        with cols_hdr[1]: st.markdown("<div style='font-size:0.7rem;color:#aaa;'>Name</div>", unsafe_allow_html=True)
        for i, r in enumerate(recent_rounds):
            with cols_hdr[2+i]:
                st.markdown(f"<div style='font-size:0.68rem;color:#888;text-align:center;'>{r['round_label']}</div>", unsafe_allow_html=True)
        with cols_hdr[-1]:
            st.markdown("<div style='font-size:0.7rem;color:#005EB8;font-weight:700;text-align:right;'>Total</div>", unsafe_allow_html=True)

    for pos, row in enumerate(ladder):
        medal = ["🥇","🥈","🥉"][pos] if pos < 3 else f"{pos+1}"
        row_class = ["top1","top2","top3"][pos] if pos < 3 else ""

        # Get recent round scores for this participant
        recent_idx  = {r["id"]: i for i, r in enumerate(rounds)}
        recent_scores = []
        for r in recent_rounds:
            s_idx = {(s["participant_id"],s["round_id"]): s["score"] for s in scores}
            sc = s_idx.get((row["id"], r["id"]), None)
            recent_scores.append(sc)

        n_cols = 2 + len(recent_rounds) + 1
        cols = st.columns([0.5, 4.5] + [1]*len(recent_rounds) + [1.5])
        with cols[0]:
            st.markdown(f"<div style='text-align:center;font-size:{'1.2' if pos<3 else '0.95'}rem;padding-top:0.2rem;'>{medal}</div>", unsafe_allow_html=True)
        with cols[1]:
            nick = f" <span style='font-size:0.72rem;color:#aaa;'>({row['afl_nickname']})</span>" if row.get('afl_nickname') else ""
            st.markdown(f"<div style='padding:0.3rem 0;font-weight:600;color:#1a2e44;'>{row['name']}{nick}</div>", unsafe_allow_html=True)
        for i, sc in enumerate(recent_scores):
            with cols[2+i]:
                if sc is not None:
                    col = "#005EB8" if sc >= 7 else ("#e07b00" if sc >= 5 else "#888")
                    st.markdown(f"<div style='text-align:center;font-weight:600;color:{col};padding:0.3rem 0;'>{sc}</div>", unsafe_allow_html=True)
                else:
                    st.markdown("<div style='text-align:center;color:#ddd;padding:0.3rem 0;'>—</div>", unsafe_allow_html=True)
        with cols[-1]:
            gold = pos == 0
            st.markdown(f"<div style='text-align:right;font-weight:800;font-size:1.05rem;color:{'#c8960c' if gold else '#005EB8'};padding:0.3rem 0;'>{row['total']}</div>", unsafe_allow_html=True)

        st.divider() if pos < len(ladder)-1 else None

# ─── ADMIN PANEL ─────────────────────────────────────────────────────────────
if st.session_state.tipping_admin:
    st.markdown("---")
    st.markdown("### ⚙️ Admin")

    tab_p, tab_r, tab_s = st.tabs(["👤 Participants", "📅 Rounds", "📊 Enter Scores"])

    # ── PARTICIPANTS ──
    with tab_p:
        # ── Add all from staff list ──
        staff_list_all = db_get_staff_list()
        existing_names = {p["name"] for p in participants}
        not_yet_added  = [s for s in staff_list_all if s["name"] not in existing_names]

        if not_yet_added:
            st.markdown(f"**Quick add from staff list** — {len(not_yet_added)} staff not yet in comp:")
            preview = ", ".join(s["name"] for s in not_yet_added[:8])
            if len(not_yet_added) > 8:
                preview += f" +{len(not_yet_added)-8} more"
            st.caption(preview)
            if st.button(f"➕ Add all {len(not_yet_added)} staff to ladder", type="primary", use_container_width=True):
                added = db_add_all_staff(staff_list_all, existing_names)
                st.success(f"✅ Added {added} staff members!"); st.rerun()
            st.markdown("---")
        else:
            st.success("✅ All active staff are already in the comp.")
            st.markdown("---")

        # ── Add individual ──
        st.markdown("**Add individual staff member:**")
        with st.form("add_p", clear_on_submit=True):
            c1, c2, c3 = st.columns([3,3,1])
            with c1: pname = st.text_input("Staff name *")
            with c2: pnick = st.text_input("AFL tipping username", placeholder="e.g. EaglesFan99")
            with c3:
                st.write("")
                st.write("")
                add_p = st.form_submit_button("➕ Add", use_container_width=True, type="primary")
            if add_p:
                if pname.strip():
                    db_add_participant(pname.strip(), pnick.strip())
                    st.success(f"Added {pname}"); st.rerun()
                else:
                    st.warning("Name required")

        # ── Current participants ──
        if participants:
            st.markdown(f"**{len(participants)} participants currently in the comp:**")
            for p in participants:
                pc1, pc2 = st.columns([6,1])
                with pc1:
                    nick = f" ({p['afl_nickname']})" if p.get("afl_nickname") else ""
                    st.markdown(f"👤 **{p['name']}**{nick}")
                with pc2:
                    if st.button("🗑️", key=f"delp_{p['id']}", help="Remove"):
                        db_del_participant(p["id"]); st.rerun()

    # ── ROUNDS ──
    with tab_r:
        with st.form("add_r", clear_on_submit=True):
            rc1, rc2, rc3 = st.columns([2,3,1])
            with rc1: rnum = st.number_input("Round number", min_value=1, max_value=28, value=len(rounds)+1)
            with rc2: rlbl = st.text_input("Label", value=f"Round {len(rounds)+1}", placeholder="e.g. Round 5")
            with rc3:
                st.write("")
                st.write("")
                add_r = st.form_submit_button("➕ Add", use_container_width=True, type="primary")
            if add_r:
                db_add_round(int(rnum), rlbl.strip() or f"Round {rnum}")
                st.success(f"Added {rlbl}"); st.rerun()

        if rounds:
            st.markdown(f"**{len(rounds)} rounds:**")
            for r in reversed(rounds):
                rc1, rc2 = st.columns([6,1])
                with rc1: st.markdown(f"📅 **{r['round_label']}**")
                with rc2:
                    if st.button("🗑️", key=f"delr_{r['id']}", help="Delete round + scores"):
                        db_del_round(r["id"]); st.rerun()

    # ── ENTER SCORES ──
    with tab_s:
        if not rounds:
            st.info("Add rounds first.")
        elif not participants:
            st.info("Add participants first.")
        else:
            sel_round = st.selectbox("Select round to enter/edit scores:",
                                      [r["round_label"] for r in reversed(rounds)])
            r_obj = next(r for r in rounds if r["round_label"] == sel_round)
            s_idx = {s["participant_id"]: s["score"] for s in scores if s["round_id"] == r_obj["id"]}

            st.markdown(f"**Enter scores for {sel_round}** *(how many tips correct out of 9)*")
            with st.form(f"scores_{r_obj['id']}", clear_on_submit=False):
                score_inputs = {}
                cols_per_row = 3
                rows_needed  = (len(participants) + cols_per_row - 1) // cols_per_row
                for row_i in range(rows_needed):
                    scols = st.columns(cols_per_row)
                    for col_i in range(cols_per_row):
                        idx = row_i * cols_per_row + col_i
                        if idx < len(participants):
                            p = participants[idx]
                            with scols[col_i]:
                                score_inputs[p["id"]] = st.number_input(
                                    p["name"], min_value=0, max_value=9,
                                    value=int(s_idx.get(p["id"], 0)),
                                    key=f"sc_{r_obj['id']}_{p['id']}"
                                )
                if st.form_submit_button("💾 Save Scores", type="primary", use_container_width=True):
                    for pid, sc in score_inputs.items():
                        db_save_score(pid, r_obj["id"], sc)
                    st.success(f"✅ Scores saved for {sel_round}!"); st.rerun()

# ─── FOOTER ──────────────────────────────────────────────────────────────────
st.markdown("""
<div style="text-align:center;padding:2rem 0 0.5rem;color:#aaa;font-size:0.76rem;">
  Cowandilla Learning Centre · Footy Tipping 2026 ·
  <a href="https://tipping.afl.com.au/leagues" target="_blank"
     style="color:#005EB8;text-decoration:none;">AFL Tipping Site ↗</a>
</div>
""", unsafe_allow_html=True)
