"""AI Detective: a murder-mystery game whose cases, suspects' dialogue, hints and endings are written by Generative AI.

Run with:  streamlit run app.py
"""

import json
import zlib
from html import escape
from pathlib import Path

import streamlit as st

import ai
import game

HERE = Path(__file__).parent
BACKUP_CASE = HERE / "backup_case.json"

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


def masthead(state, right):
    number = zlib.crc32(state["case"]["title"].encode()) % 9000 + 1000 if state else "----"
    html(f'<div class="file-label"><span>Case file no. {number}</span><span>{escape(right)}</span></div>')


def exhibit(index, clue, small=False):
    html(
        f'<div class="exhibit{" small" if small else ""}"><span class="tag">Exhibit {chr(65 + index)} · '
        f'{escape(clue["location"])}</span>{escape(clue["text"])}</div>'
    )


# ---------- Start screen ----------

def start_screen():
    masthead(None, "New investigation")
    st.title("AI Detective")
    st.write(
        "Name a place and a new murder is written for you: a victim, four suspects with alibis and secrets, "
        "and the evidence that gives the killer away. Question the suspects in your own words, search the scene, "
        "and name the killer before your time runs out."
    )
    html('<p class="source"><b>AI-written</b>every case is generated live by GPT-OSS 120B on Groq</p>')
    show_flash()
    with st.form("new_case"):
        theme = st.text_input(
            "Where does it happen? (optional)",
            placeholder="a Bollywood film set, a Mars research base, an IPL team hotel...",
            max_chars=150,
        )
        difficulty = st.radio(
            "Time on the case", list(game.DIFFICULTY_TURNS), index=1, horizontal=True,
            format_func=lambda d: f"{d}: {game.DIFFICULTY_TURNS[d]} turns",
        )
        start = st.form_submit_button("Open the case file", type="primary")
    if start:
        with st.spinner("Writing your case..."):
            try:
                case = ai.generate_case(theme)
            except ai.AIError as e:
                flash("error", f"{e} You can retry, or play the backup case below.")
            else:
                st.session_state.game = game.new_game(case, difficulty)
        st.rerun()

    st.write("")
    if st.button("Play the backup case", help="A hand-written case for when the AI service is unavailable."):
        case = json.loads(BACKUP_CASE.read_text())
        st.session_state.game = game.new_game(case, "Normal", offline=True)
        st.rerun()


# ---------- Playing screen ----------

def sidebar(state):
    with st.sidebar:
        st.header("Notebook")
        st.metric("Turns left", f"{state['turns_left']} / {state['max_turns']}")
        st.progress(state["turns_left"] / state["max_turns"])
        st.subheader("Evidence")
        if state["found_clues"]:
            for i, c in enumerate(state["found_clues"]):
                exhibit(i, c, small=True)
        else:
            st.caption("Nothing logged yet. Search the scene to find evidence.")
        if state["hints"]:
            st.subheader("Partner's notes")
            for h in state["hints"]:
                st.markdown(f"- *{h}*")
        st.divider()
        if st.button("Abandon this case"):
            del st.session_state.game
            st.rerun()


def interrogate_tab(state):
    suspects = state["case"]["suspects"]
    name = st.radio("Suspect", [s["name"] for s in suspects], horizontal=True, label_visibility="collapsed")
    s = next(x for x in suspects if x["name"] == name)
    html(
        f'<div class="dossier"><div class="name">{escape(s["name"])}</div>'
        f'<div class="role">{escape(s["role"])}</div><div><i>{escape(s["personality"])}</i></div></div>'
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
        st.caption(f"No interview with {name} on record yet.")

    with st.form(f"ask_{name}", clear_on_submit=True):
        question = st.text_input(
            f"Question for {name} (costs 1 turn)",
            placeholder="Where were you when the victim died?",
            max_chars=game.MAX_QUESTION_LENGTH,
        )
        asked = st.form_submit_button("Ask", disabled=not game.can_act(state))
    if asked:
        try:
            question = game.clean_question(question)
            with st.spinner(f"{name} considers the question..."):
                answer = ai.interrogate(state, name, question)
            game.record_answer(state, name, question, answer)
        except (ValueError, ai.AIError) as e:
            flash("warning", str(e))  # no turn is spent when the question or the AI call fails
        st.rerun()


def search_tab(state):
    st.caption("Searching a location costs 1 turn and turns up everything hidden there.")
    for loc in state["case"]["locations"]:
        with st.container(border=True):
            st.markdown(f"**{loc['name']}**  \n{loc['description']}")
            if loc["name"] in state["searched"]:
                for i, c in enumerate(state["found_clues"]):
                    if c["location"] == loc["name"]:
                        exhibit(i, c)
            elif st.button(f"Search {loc['name']}", key=f"search_{loc['name']}",
                           disabled=not game.can_act(state)):
                try:
                    found = game.search(state, loc["name"])
                    flash("success", f"{len(found)} item(s) logged from {loc['name']}.")
                except ValueError as e:
                    flash("warning", str(e))
                st.rerun()
    source_note(state, "locations and evidence were written along with the case")


def partner_tab(state):
    st.write("Your partner reads through your notebook and tells you where to look next. Costs 1 turn.")
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
    st.write("Name the killer. There is no second chance.")
    with st.form("accuse"):
        name = st.selectbox("The killer is", [s["name"] for s in state["case"]["suspects"]])
        reasoning = st.text_area("Your reasoning (it will be graded)", max_chars=600,
                                 placeholder="Which evidence breaks their story?")
        sure = st.checkbox("This is my final accusation.")
        submitted = st.form_submit_button("Make the accusation", type="primary")
    if submitted:
        if not sure:
            flash("warning", "Tick the box to confirm your accusation.")
            st.rerun()
        game.accuse(state, name)
        with st.spinner("The room goes quiet..."):
            try:
                state["ending"] = ai.write_ending(state, reasoning.strip())
            except ai.AIError as e:
                flash("warning", f"The narrator is unavailable ({e}). Showing the plain solution instead.")
        st.rerun()


def playing_screen(state):
    case = state["case"]
    sidebar(state)
    masthead(state, "Open investigation")
    st.title(case["title"])
    html(f'<p class="setting">{escape(case["setting"])}</p>')
    show_flash()
    with st.expander("Briefing", expanded=state["turns_left"] == state["max_turns"]):
        st.markdown(f"**The victim:** {case['victim']['name']}. {case['victim']['description']}")
        st.write(case["intro"])
        source_note(state, "case, victim and suspects")
    if not game.can_act(state):
        st.warning("You are out of turns. Open the Accuse tab and name the killer.")

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
    if state["status"] == "won":
        html('<div class="stamp solved">SOLVED</div>')
        html(f'<p class="verdict">Case solved. {escape(real)} was the killer.</p>')
    else:
        html('<div class="stamp unsolved">UNSOLVED</div>')
        html(f'<p class="verdict">You accused {escape(state["accused"])}. The killer was {escape(real)}.</p>')

    col1, col2, col3 = st.columns(3)
    col1.metric("Score", game.score(state))
    col2.metric("Turns used", state["max_turns"] - state["turns_left"])
    col3.metric("Evidence found", f"{len(state['found_clues'])} / {len(case['clues'])}")

    if state["ending"]:
        st.subheader("The final scene")
        st.write(state["ending"])
        source_note(None, "the ending and the grade for your reasoning")
    st.subheader("What really happened")
    st.write(case["solution"])
    source_note(state, "solution")
    if st.button("Take a new case", type="primary"):
        del st.session_state.game
        st.rerun()


state = st.session_state.get("game")
if state is None:
    start_screen()
elif state["status"] == "playing":
    playing_screen(state)
else:
    ending_screen(state)
