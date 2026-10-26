"""AI Detective: a mystery game whose cases, suspects' dialogue, hints and endings are written by Generative AI.

Run with:  streamlit run app.py
"""

import json
import os
import random
import zlib
from datetime import date
from html import escape
from pathlib import Path

import streamlit as st

import ai
import game

HERE = Path(__file__).parent
BACKUP_CASES = HERE / "backup_cases.json"
HISTORY_FILE = Path(os.getenv("AI_DETECTIVE_HISTORY", HERE / "case_history.json"))  # tests point this elsewhere

# Ready-made settings shown as cards on the start screen; the AI builds the case around the one picked
SCENARIOS = {
    "Bollywood film set": "the set of a big-budget Bollywood film in Mumbai, the night before the final shoot",
    "IPL final": "the team hotel in Ahmedabad on the night of the IPL final",
    "Royal wedding": "a lavish three-day wedding in a Rajasthan palace",
    "Monsoon night train": "an overnight train from Mumbai to Goa, stuck in heavy monsoon rain",
    "College tech fest": "a college tech fest in Pune, the night before the hackathon finals",
    "Mars research base": "a six-person research base on Mars in the year 2089",
    "Startup launch": "a Bengaluru startup office the night before a big product launch",
    "Hill station hotel": "an old colonial hotel in Shimla during a snowstorm",
}
SURPRISE, OWN_IDEA = "Surprise me", "My own idea"

LOADING_LINES = [
    "Dusting the doorknobs for prints...", "Bribing the night watchman for gossip...",
    "Sharpening pencils, loosening ties...", "Teaching four suspects to lie convincingly...",
    "Hiding the murder weapon somewhere clever...", "Pouring a strong cup of cutting chai...",
]
QUICK_QUESTIONS = {
    "Your alibi?": "Where exactly were you when it happened, and who can confirm it?",
    "Who did it?": "Who do you think did this, and why?",
    "Seen anything odd?": "Did you see or hear anything unusual that night?",
    "About the victim?": "What was your relationship with {victim}, honestly?",
}
EVENT_ICONS = {"witness": "🕵️", "threat": "⚠️", "destroyed": "🔥", "warrant": "🔓"}

st.set_page_config(page_title="Case File: AI Detective", page_icon="🔍", layout="centered")
st.markdown(f"<style>{(HERE / 'style.css').read_text()}</style>", unsafe_allow_html=True)


def html(markup):
    st.markdown(markup, unsafe_allow_html=True)


def source_note(state, what):
    """Label who wrote a piece of content (the brief requires AI content to be identified)."""
    if state is not None and state["offline"]:
        html(f'<p class="source"><b>Hand-written</b>{escape(what)} (offline backup case, not AI-generated)</p>')
    else:
        html(f'<p class="source"><b>AI-written</b>{escape(what)}</p>')


def flash(kind, message):
    """Show a message on the next rerun (actions always rerun so the screen reflects the new state)."""
    st.session_state.flash = (kind, message)


def show_flash():
    if "flash" in st.session_state:
        kind, message = st.session_state.pop("flash")
        getattr(st, kind)(message)


def load_history():
    try:
        return json.loads(HISTORY_FILE.read_text())
    except (OSError, ValueError):
        return []  # first game, or an unreadable file: start a fresh career


def save_result(state):
    history = load_history()
    history.append({
        "title": state["case"]["title"], "crime": state["case"].get("crime", "Murder"),
        "difficulty": state["difficulty"], "won": state["status"] == "won", "score": game.score(state),
        "stars": game.stars(state), "rank": game.rank(state), "date": date.today().isoformat(),
    })
    try:
        HISTORY_FILE.write_text(json.dumps(history[-50:], indent=1))
    except OSError:
        pass  # a read-only folder shouldn't end the game; the career just isn't saved


def career_strip(history):
    c = game.career(history)
    streak = f"🔥 {c['streak']}" if c["streak"] >= 2 else str(c["streak"])
    cells = [("Cases", c["played"]), ("Solved", c["solved"]), ("Best score", c["best"]), ("Streak", streak)]
    html('<div class="career">' + "".join(
        f'<div><span class="num">{v}</span><span class="lbl">{escape(k)}</span></div>' for k, v in cells) + "</div>")


def masthead(state, right):
    number = zlib.crc32(state["case"]["title"].encode()) % 9000 + 1000 if state else "----"
    html(f'<div class="file-label"><span>Case file no. {number}</span><span>{escape(right)}</span></div>')


def pips(filled, total, cls="pip"):
    return "".join(f'<i class="{cls}{" on" if i < filled else ""}"></i>' for i in range(total))


def exhibit(index, clue, small=False):
    via = f' · {escape(clue["via"])}' if clue.get("via") else ""
    html(
        f'<div class="exhibit{" small" if small else ""}{" confession" if clue.get("via") == "Confession" else ""}">'
        f'<span class="tag">Exhibit {chr(65 + index)} · {escape(clue["location"])}{via}</span>'
        f'{escape(clue["text"])}</div>'
    )


# ---------- Start screen ----------

def start_screen():
    masthead(None, "New investigation")
    html('<div class="hero"><div class="kicker">Four suspects. One liar. Not enough time.</div>'
         '<h1 class="whodunit">Who<span>dun</span>it?</h1></div>')
    st.write(
        "Every case is written fresh for you. Grill the suspects in your own words, slap the evidence on the "
        "table and watch them sweat. But move fast: the culprit is covering their tracks while you work."
    )
    history = load_history()
    if history:
        career_strip(history)
    html('<p class="source"><b>AI-written</b>every case is generated live by GPT-OSS 120B on Groq</p>')
    show_flash()

    with st.container(border=True):
        pick = st.pills("Where does it happen?", [SURPRISE, *SCENARIOS, OWN_IDEA], default=SURPRISE)
        theme = ""
        if pick == OWN_IDEA:
            theme = st.text_input("Describe your setting", max_chars=150,
                                  placeholder="a houseboat in Kerala, a K-pop concert, an Antarctic station...")
        elif pick in SCENARIOS:
            theme = SCENARIOS[pick]
        crime = st.segmented_control("The crime", list(game.CRIMES), default="Murder")
        difficulty = st.segmented_control(
            "Time on the case", list(game.DIFFICULTY_TURNS), default="Normal",
            format_func=lambda d: f"{d} · {game.DIFFICULTY_TURNS[d]} turns",
        )
        if st.button("Open the case file", type="primary", use_container_width=True):
            if pick == OWN_IDEA and not theme.strip():
                flash("warning", "Describe your setting first, or pick one of the cards.")
            else:
                with st.spinner(random.choice(LOADING_LINES)):
                    try:
                        case = ai.generate_case(theme, crime or "Murder")
                    except ai.AIError as e:
                        flash("error", f"{e} You can retry, or play a backup case below.")
                    else:
                        st.session_state.game = game.new_game(case, difficulty or "Normal")
            st.rerun()

    st.write("")
    if st.button("Play a backup case", help="One of three hand-written cases, for when the AI service is unavailable."):
        case = random.choice(json.loads(BACKUP_CASES.read_text()))
        st.session_state.game = game.new_game(case, "Normal", offline=True)
        st.rerun()

    if history:
        with st.expander("Your case log"):
            for r in reversed(history[-8:]):
                verdict = "★" * r["stars"] + "☆" * (3 - r["stars"]) if r["won"] else "✗ unsolved"
                st.markdown(f"**{r['title']}** · {r['crime']} · {r['difficulty']} · {verdict} · {r['score']} pts")


# ---------- Playing screen ----------

def sidebar(state):
    with st.sidebar:
        st.header("Notebook")
        html(f'<div class="turns-label">Turns left <b>{state["turns_left"]}</b> / {state["max_turns"]}</div>'
             f'<div class="pips">{pips(state["turns_left"], state["max_turns"])}</div>')
        st.subheader("Evidence")
        if state["found_clues"]:
            for i, c in enumerate(state["found_clues"]):
                exhibit(i, c, small=True)
        else:
            st.caption("Nothing logged yet. Search the scene to find evidence.")
        if state["events"]:
            st.subheader("Case wire")
            for e in reversed(state["events"]):
                st.markdown(f"{EVENT_ICONS[e['kind']]} *Turn {e['turn']}:* {e['text']}")
        if state["hints"]:
            st.subheader("Partner's notes")
            for h in state["hints"]:
                st.markdown(f"- *{h}*")
        st.divider()
        if st.button("Abandon this case"):
            del st.session_state.game
            st.rerun()


def suspect_label(state, name):
    if name in state["cracked"]:
        return f"{name} 💥"
    return f"{name} " + "●" * state["nerve"][name] + "○" * (game.NERVE_TO_CRACK - state["nerve"][name])


def ask(state, name, question, exhibit_pick):
    """Stream a suspect's answer, then log it. A bad question or a failed AI call costs no turn."""
    before = state["nerve"][name]
    try:
        question = game.with_evidence(state, question, exhibit_pick)
        game.require_turn(state)
        with st.container(border=True):
            st.caption(f"{name.upper()} ANSWERS")
            answer = st.write_stream(ai.interrogate(state, name, question))
        cracked = game.record_answer(state, name, question, answer.strip(), exhibit_pick)
    except (ValueError, ai.AIError) as e:
        flash("warning", str(e))
    else:
        if cracked:
            st.session_state.crack = name
        elif state["nerve"][name] > before:
            flash("info", f"{name} flinches. That hit a nerve. One more piece of evidence and they'll crack.")
    st.rerun()


def interrogate_tab(state):
    suspects = state["case"]["suspects"]
    if "crack" in st.session_state:
        cracked = st.session_state.pop("crack")
        html(f'<div class="crack-banner"><b>{escape(cracked)} cracks!</b>Their secret is out. '
             "It's logged as a new exhibit.</div>")
    # A stable key keeps the pick when the nerve marks in the labels change; it is per case so names never go stale
    name = st.radio("Suspect", [s["name"] for s in suspects], horizontal=True, label_visibility="collapsed",
                    key=f"suspect_{state['case']['title']}", format_func=lambda n: suspect_label(state, n))
    s = next(x for x in suspects if x["name"] == name)
    cracked = name in state["cracked"]
    nerve = game.NERVE_TO_CRACK if cracked else state["nerve"][name]
    html(
        f'<div class="dossier"><div class="top"><div><div class="name">{escape(s["name"])}</div>'
        f'<div class="role">{escape(s["role"])}</div></div>'
        f'<div class="nerve"><span>{"CRACKED" if cracked else "Nerve"}</span>'
        f'{pips(nerve, game.NERVE_TO_CRACK, "bar")}</div></div>'
        f'<div><i>{escape(s["personality"])}</i></div></div>'
    )

    transcript = state["transcripts"][name]
    if transcript:
        lines = "".join(
            f'<div class="line"><span class="who">Detective</span><span class="q">{escape(t["question"])}</span></div>'
            f'<div class="line"><span class="who">{escape(name.split()[0])}</span><span class="a">{escape(t["answer"])}</span></div>'
            for t in transcript
        )
        html(f'<div class="transcript">{lines}</div>')
        source_note(None, f"{name}'s answers are generated live by the AI playing the character")
    else:
        st.caption(f"No interview with {name} on record yet. Show them evidence that points at them to rattle them.")

    can = game.can_act(state)
    victim = state["case"]["victim"]["name"]
    for col, (label, question) in zip(st.columns(len(QUICK_QUESTIONS)), QUICK_QUESTIONS.items()):
        if col.button(label, key=f"quick_{label}", disabled=not can, use_container_width=True):
            ask(state, name, question.format(victim=victim), None)

    found = state["found_clues"]
    with st.form(f"ask_{name}", clear_on_submit=True):
        question = st.text_input(
            f"Or ask {name} anything (costs 1 turn)",
            placeholder="Where were you when it happened?",
            max_chars=game.MAX_QUESTION_LENGTH,
        )
        exhibit_pick = st.selectbox(
            "Slam evidence on the table (optional)", [None, *range(len(found))],
            format_func=lambda i: "Don't show anything" if i is None
            else f"Exhibit {chr(65 + i)}: {found[i]['text'][:70]}...",
            disabled=not found,
            help="Evidence that really points at this suspect raises their nerve. Two hits and they crack.",
        )
        asked = st.form_submit_button("Ask", disabled=not can)
    if asked:
        ask(state, name, question, exhibit_pick)


def search_tab(state):
    st.caption("Searching a location costs 1 turn and turns up everything still hidden there.")
    threat = game.cleanup_warning(state)
    for loc in state["case"]["locations"]:
        place = loc["name"]
        sealed = game.is_sealed(state, place)
        at_risk = threat and threat[0] == place
        with st.container(border=True):
            badge = ""
            if sealed:
                need = game.WARRANT_CLUES - len(state["found_clues"])
                badge = f'<span class="badge sealed">🔒 Sealed · {need} more exhibit{"s" * (need > 1)} for a warrant</span>'
            elif at_risk:
                badge = f'<span class="badge risk">⚠️ Evidence at risk · {threat[1]} turn{"s" * (threat[1] > 1)}</span>'
            html(f'<div class="loc"><b>{escape(place)}</b>{badge}<div>{escape(loc["description"])}</div></div>')
            if place in state["searched"]:
                shown = [(i, c) for i, c in enumerate(state["found_clues"]) if c["location"] == place]
                for i, c in shown:
                    exhibit(i, c)
                if any(c["location"] == place and c["text"] in state["destroyed"] for c in state["case"]["clues"]):
                    html('<div class="burned">🔥 Ashes in a bin. Something here was destroyed before you arrived.</div>')
                elif not shown:
                    st.caption("Nothing left to find here.")
            elif st.button(f"Search {place}", key=f"search_{place}", disabled=sealed or not game.can_act(state),
                           type="primary" if at_risk else "secondary"):
                try:
                    found = game.search(state, place)
                    flash("success" if found else "info",
                          f"{len(found)} item(s) logged from {place}." if found else f"Nothing new in {place}.")
                except ValueError as e:
                    flash("warning", str(e))
                st.rerun()
    source_note(state, "locations and evidence were written along with the case")


def partner_tab(state):
    st.write("Stuck? Your partner reads your notebook and points you somewhere useful. "
             f"Costs 1 turn, and you lose the +{game.POINTS['no_hints']} lone wolf bonus.")
    if st.button("Ask partner for a hint", disabled=not game.can_act(state)):
        try:
            with st.spinner("Your partner flips through the notebook..."):
                hint = ai.partner_hint(state)
            game.record_hint(state, hint)
        except (ValueError, ai.AIError) as e:
            flash("warning", str(e))
        st.rerun()
    for h in state["hints"]:
        html(f'<div class="exhibit"><span class="tag">Partner</span><i>{escape(h)}</i></div>')
    if state["hints"]:
        source_note(None, "hints are generated from your progress")


def accuse_tab(state):
    p = game.POINTS
    st.write("Build your case on the deduction board. There is no second chance.")
    html(f'<div class="board-points">Culprit <b>{p["solved"]}</b> · Motive <b>+{p["motive"]}</b> · '
         f'Key evidence <b>+{p["evidence"]}</b> · Each spare turn <b>+{p["per_turn"]}</b></div>')
    found = state["found_clues"]
    with st.form("accuse"):
        name = st.selectbox("Who did it?", [s["name"] for s in state["case"]["suspects"]])
        motive = st.selectbox("Why?", game.motive_options(state["case"]), index=None,
                              placeholder="Pick the motive")
        key = st.selectbox("Which exhibit proves it?", list(range(len(found))), index=None,
                           placeholder="Pick the evidence" if found else "You haven't found any evidence",
                           format_func=lambda i: f"Exhibit {chr(65 + i)}: {found[i]['text'][:80]}")
        reasoning = st.text_area("Say it to their face (optional, the narrator grades it)", max_chars=600,
                                 placeholder="Which evidence breaks their story?")
        sure = st.checkbox("This is my final accusation.")
        submitted = st.form_submit_button("Make the accusation", type="primary")
    if submitted:
        if not sure:
            flash("warning", "Tick the box to confirm your accusation.")
            st.rerun()
        game.accuse(state, name, motive, key)
        save_result(state)
        with st.spinner("The room goes quiet..."):
            try:
                state["ending"] = ai.write_ending(state, reasoning.strip())
            except ai.AIError as e:
                flash("warning", f"The narrator is unavailable ({e}). Showing the plain solution instead.")
        st.rerun()


def playing_screen(state):
    case = state["case"]
    for event in game.pop_news(state):
        st.toast(event["text"], icon=EVENT_ICONS[event["kind"]])
    sidebar(state)
    masthead(state, f"Open investigation · {state['difficulty']}")
    st.title(case["title"])
    html(f'<p class="setting">{escape(case.get("crime", "Murder"))} · {escape(case["setting"])}</p>')
    html(f'<div class="hud"><span>Turns</span><div class="pips">{pips(state["turns_left"], state["max_turns"])}</div>'
         f'<b>{state["turns_left"]}</b></div>')
    threat = game.cleanup_warning(state)
    if threat:
        html(f'<div class="alarm">⚠️ Someone is heading for the <b>{escape(threat[0])}</b> to destroy evidence. '
             f'Search it within <b>{threat[1]}</b> turn{"s" * (threat[1] > 1)}!</div>')
    show_flash()
    with st.expander("Briefing", expanded=state["turns_left"] == state["max_turns"]):
        label = game.CRIMES[case.get("crime", "Murder")]["victim_label"]
        st.markdown(f"**{label}:** {case['victim']['name']}. {case['victim']['description']}")
        st.write(case["intro"])
        source_note(state, "case, victim and suspects")
    if not game.can_act(state):
        st.warning("You are out of turns. Open the Accuse tab and name the culprit.")

    # A key makes the open tab survive the rerun that follows every action
    tabs = st.tabs(["Interrogate", "Search", "Partner", "Accuse"], key="tab", on_change="rerun")
    with tabs[0]:
        interrogate_tab(state)
    with tabs[1]:
        search_tab(state)
    with tabs[2]:
        partner_tab(state)
    with tabs[3]:
        accuse_tab(state)


# ---------- Ending screen ----------

def ending_screen(state):
    case = state["case"]
    real = game.culprit(case)["name"]
    masthead(state, "Closed")
    st.title(case["title"])
    show_flash()
    won = state["status"] == "won"
    if won:
        if not state.get("celebrated"):
            state["celebrated"] = True
            st.balloons()
        html('<div class="stamp solved">SOLVED</div>')
        html(f'<p class="verdict">Case solved. {escape(real)} was the culprit.</p>')
        n = game.stars(state)
        html(f'<div class="stars">{"★" * n}<span>{"★" * (3 - n)}</span></div>')
    else:
        html('<div class="stamp unsolved">UNSOLVED</div>')
        html(f'<p class="verdict">You accused {escape(state["accused"])}. The culprit was {escape(real)}.</p>')

    html(f'<p class="rank">Rank: {escape(game.rank(state))}</p>')
    col1, col2, col3 = st.columns(3)
    col1.metric("Score", game.score(state))
    col2.metric("Turns used", game.turns_used(state))
    col3.metric("Evidence found", f"{len(state['found_clues'])} / {len(case['clues'])}")

    if won:
        d = state["deduction"]
        rows = "".join(f'<tr><td>{escape(r)}</td><td>+{pts}</td></tr>' for r, pts in game.score_breakdown(state))
        misses = "".join(f'<tr class="miss"><td>{m}</td><td>+0</td></tr>' for m, ok in
                         (("Missed the motive", d["motive"]), ("Missed the key evidence", d["evidence"])) if not ok)
        html(f'<table class="breakdown">{rows}{misses}<tr class="total"><td>Total</td>'
             f'<td>{game.score(state)}</td></tr></table>')
    career_strip(load_history())

    if state["ending"]:
        st.subheader("The final scene")
        st.write(state["ending"])
        source_note(None, "the ending and the grade for your reasoning")
    st.subheader("What really happened")
    st.write(case["solution"])
    source_note(state, "solution")
    if st.button("Take a new case", type="primary", use_container_width=True):
        del st.session_state.game
        st.rerun()


state = st.session_state.get("game")
if state is None:
    start_screen()
elif state["status"] == "playing":
    playing_screen(state)
else:
    ending_screen(state)
